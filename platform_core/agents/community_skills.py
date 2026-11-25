"""Discover operator-installed Agent Skills and lazily read their Markdown for chat."""

from dataclasses import dataclass
from functools import lru_cache
from itertools import islice
import logging
import os
from pathlib import Path
import re
import stat

from .. import access_policy
from . import deerflow_chat

BUNDLED = Path(__file__).resolve().parents[2] / "skills"
if not BUNDLED.is_dir():
    BUNDLED = Path(__file__).parent / "bundled/skills"
MAX_SKILLS = 32
MAX_FILE = 64 * 1024
MAX_REFERENCES = 48
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
logger = logging.getLogger(__name__)


def _roots():
    configured = (Path(s) for s in os.environ.get("NH_AGENT_SKILL_DIRS", "").split(os.pathsep) if s)
    return dict.fromkeys([BUNDLED, *islice((root for root in configured if root.is_absolute()), 8)])


def _regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
        raise ValueError("技能资料须为指定目录中的 Markdown 文件")
    return info


def _read(path):
    # Open the checked leaf without following a replacement symlink. Bound reads
    # even if a package is replaced while the catalog is being refreshed.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("技能资料必须为普通文件")
        content = stream.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise ValueError("技能资料过长")
    return content.decode("utf-8")


@dataclass(frozen=True)
class Skill:
    path: Path
    name: str
    description: str
    grant: str


@lru_cache(maxsize=128)
def _metadata(path, identity):
    value = deerflow_chat.capability("describe_skill", {"name": path.parent.name, "source": _read(path)})
    name, description, grant = value["name"], value["description"], value["grant"]
    if (name != path.parent.name or len(name) > 64 or not NAME.fullmatch(name)
            or not 1 <= len(description) <= 1024 or not isinstance(grant, str) or grant not in access_policy.PERMISSIONS):
        raise ValueError("请核对技能名称、说明和岗位授权")
    return Skill(path, name, description, grant)


def _describe(path):
    info = _regular(path)
    return _metadata(path, (info.st_dev, info.st_ino, info.st_ctime_ns, info.st_size))


def _discover(user):
    if not user or user.get("kind") not in ("staff", "owner") or not access_policy.has(user, "assistants"):
        return {}
    skills = {}
    seen = set()
    for root in _roots():
        if root.is_symlink() or not root.is_dir():
            continue
        try:
            children = sorted(islice(root.iterdir(), 128))
        except OSError:
            continue
        for child in children:
            if child.name in seen or child.is_symlink() or not child.is_dir():
                continue
            try:
                skill = _describe(child / "SKILL.md")
            except deerflow_chat.Unavailable:
                return {}
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                logger.warning("Ignored invalid Agent Skill package %s", child.name)
                continue
            seen.add(skill.name)
            if access_policy.has(user, skill.grant):
                skills[skill.name] = skill
                if len(skills) == MAX_SKILLS:
                    return skills
    return skills


def catalog(user):
    return [{"name": skill.name, "description": skill.description} for skill in _discover(user).values()]


def _references(package):
    names = []
    for directory in ("references", "examples"):
        folder = package / directory
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            files = sorted(islice(folder.iterdir(), 96))
        except OSError:
            continue
        for path in files:
            if path.suffix.lower() != ".md":
                continue
            try:
                _regular(path)
            except (OSError, ValueError):
                continue
            names.append(f"{directory}/{path.name}")
            if len(names) == MAX_REFERENCES:
                return names
    return names


@dataclass(frozen=True)
class ReadSkill:
    skills: dict
    name = "read_workflow_skill"
    description = "查看院内已启用的工作方法或写作指南，必要时按返回的相对文件名读取示例。"

    def function(self):
        offerings = "\n".join(f"{s.name} — {s.description}" for s in self.skills.values())
        return {"type": "function", "function": {
            "name": self.name, "description": self.description + "\n" + offerings,
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "enum": list(self.skills)},
                "reference": {"type": "string", "description": "可选，填写该技能返回的 references 或 examples 中的文件名。"},
            }, "required": ["name"], "additionalProperties": False},
        }}

    def execute(self, arguments):
        if not isinstance(arguments, dict) or not set(arguments) <= {"name", "reference"}:
            raise ValueError("请指定可用的工作方法")
        name = arguments.get("name")
        if not isinstance(name, str) or name not in self.skills:
            raise ValueError("该工作方法未向当前账号开放")
        skill = self.skills[name]
        package = skill.path.parent
        # Reload metadata at use time too. A hot-swapped skill may now have a different grant.
        if package.parent not in _roots() or package.parent.is_symlink() or package.is_symlink() or _describe(skill.path) != skill:
            raise ValueError("技能已更新，请重新提问")
        references = _references(package)
        if "reference" in arguments:
            reference = arguments["reference"]
            if not isinstance(reference, str) or reference not in references:
                raise ValueError("请选择该技能列出的 Markdown 资料")
            path = package / reference
        else:
            reference, path = None, skill.path
        contents = _read(path)
        if reference is None:
            parsed = deerflow_chat.capability("read_skill", {"source": contents, "name": name})
            if parsed["grant"] != skill.grant:
                raise ValueError("技能权限已更新，请重新提问")
            contents = parsed["instructions"]
        else:
            contents = contents.strip()
        return {"name": name, "reference": reference, "references": references, "instructions": contents}


def tools_for(user, text=""):
    skills = _discover(user)
    return (ReadSkill(skills),) if skills else ()


def document_guidance(user):
    """Load the reviewed spreadsheet procedure for an authorized document preview."""
    skills = _discover(user)
    if "xlsx" not in skills or skills["xlsx"].path != BUNDLED / "xlsx" / "SKILL.md":
        return ""
    return ReadSkill(skills).execute({"name": "xlsx"})["instructions"]


def scheduled_guidance(name):
    """Read only the assigned, bundled procedure for a scheduled resident specialist."""
    grants = {"resident-health-review": "clinical", "resident-daily-life": "care"}
    if name not in grants:
        raise ValueError("未知的长辈定时技能")
    skill = _describe(BUNDLED / name / "SKILL.md")
    if skill.name != name or skill.grant != grants[name]:
        raise ValueError("长辈定时技能与岗位范围不匹配")
    return ReadSkill({name: skill}).execute({"name": name})["instructions"]
