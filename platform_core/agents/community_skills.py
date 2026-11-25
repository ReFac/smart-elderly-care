"""Discover operator-installed Agent Skills and lazily read their Markdown for chat."""

from dataclasses import dataclass
from contextlib import ExitStack
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
    root = next((p for p in _roots() if path.is_relative_to(p)), None)
    if root is None:
        raise ValueError("技能资料不在机构目录内")
    parts = path.relative_to(root).parts
    if not parts or ".." in parts:
        raise ValueError("技能资料路径无效")
    with ExitStack() as stack:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(root, flags)
        stack.callback(os.close, directory)
        for folder in parts[:-1]:
            directory = os.open(folder, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stream = stack.enter_context(os.fdopen(descriptor, "rb"))
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
    allowed_tools: tuple | None


@lru_cache(maxsize=128)
def _metadata(path, identity):
    value = deerflow_chat.capability("skill_metadata", {"name": path.parent.name, "source": _read(path)})
    name, description, grant = value["name"], value["description"], value["grant"]
    if (name != path.parent.name or len(name) > 64 or not NAME.fullmatch(name)
            or not 1 <= len(description) <= 1024 or not isinstance(grant, str) or grant not in access_policy.PERMISSIONS):
        raise ValueError("请核对技能名称、说明和岗位授权")
    allowed = value["allowedTools"]
    return Skill(path, name, description, grant, None if allowed is None else tuple(allowed))


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


def _member(skill, reference=None):
    package = skill.path.parent
    if package.parent not in _roots() or package.parent.is_symlink() or package.is_symlink() or _describe(skill.path) != skill:
        raise ValueError("技能已更新，请重新提问")
    refs = _references(package)
    if reference is not None and reference not in refs:
        raise ValueError("请选择该技能列出的 Markdown 资料")
    contents = _read(package / reference if reference else skill.path)
    if _describe(skill.path) != skill:
        raise ValueError("技能已更新，请重新提问")
    return contents, refs


def _instructions(skill):
    source, _ = _member(skill)
    parsed = deerflow_chat.capability("read_skill", {"source": source, "name": skill.name})
    if parsed["grant"] != skill.grant:
        raise ValueError("技能权限已更新，请重新提问")
    return parsed["instructions"]


@lru_cache(maxsize=1)
def _sdk_tools():
    return {spec["function"]["name"]: spec["function"] for spec in deerflow_chat.capability("skill_tools", {})}


@dataclass(frozen=True)
class ScopedSkillTool:
    name: str
    skills: dict

    def function(self):
        definition = dict(_sdk_tools()[self.name])
        if self.name == "describe_skill":
            definition["description"] += "\n当前账号的技能：" + "、".join(self.skills)
        else:
            definition["description"] = "读取 describe_skill 列出的 SKILL.md 或该技能列出的 Markdown 附件，可按行号读取。"
        return {"type": "function", "function": definition}

    def within_scope(self, other):
        shared = {name: skill for name, skill in self.skills.items() if other.skills.get(name) == skill}
        return ScopedSkillTool(self.name, shared) if shared else None

    def execute(self, args):
        if self.name == "describe_skill":
            name = args.get("name")
            if set(args) != {"name"} or not isinstance(name, str) or not 1 <= len(name) <= 1024:
                raise ValueError("请填写需要查找的技能")
            catalog = [(skill.name, skill.description, skill.allowed_tools) for skill in self.skills.values()]
            return deerflow_chat.capability("skill_tools", {"query": name, "catalog": catalog})

        path = args.get("path")
        if not isinstance(path, str) or set(args) - {"path", "description", "start_line", "end_line"}:
            raise ValueError("请使用技能目录返回的文件路径")
        prefix = "/mnt/skills/public/"
        name, slash, member = path.removeprefix(prefix).partition("/")
        if not path.startswith(prefix) or not slash or name not in self.skills:
            raise ValueError("该技能文件未向当前账号开放")
        reference = None if member == "SKILL.md" else member
        skill = self.skills[name]
        source, refs = _member(skill, reference)
        lines = {k: args[k] for k in ("start_line", "end_line") if args.get(k) is not None}
        if any(type(n) is not int or n < 1 for n in lines.values()) or lines.get("start_line", 1) > lines.get("end_line", float("inf")):
            raise ValueError("请核对起止行号")
        request = {"source": source, **lines}
        if reference is None:
            request.update(name=name, grant=skill.grant)
        content = deerflow_chat.capability("read_skill_member", request)
        return {"path": path, "content": content, "references": [prefix + name + "/" + ref for ref in refs]}


def tools_for(user, text=""):
    skills = _discover(user)
    return tuple(ScopedSkillTool(name, skills) for name in _sdk_tools()) if skills else ()


def document_guidance(user):
    """Load the reviewed spreadsheet procedure for an authorized document preview."""
    skills = _discover(user)
    if "xlsx" not in skills or skills["xlsx"].path != BUNDLED / "xlsx" / "SKILL.md":
        return ""
    return _instructions(skills["xlsx"])


def scheduled_guidance(name):
    """Read only the assigned, bundled procedure for a scheduled resident specialist."""
    grants = {"resident-health-review": "clinical", "resident-daily-life": "care"}
    if name not in grants:
        raise ValueError("未知的长辈定时技能")
    skill = _describe(BUNDLED / name / "SKILL.md")
    if skill.name != name or skill.grant != grants[name]:
        raise ValueError("长辈定时技能与岗位范围不匹配")
    return _instructions(skill)
