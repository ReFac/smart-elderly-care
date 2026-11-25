"""A side-effect-free arithmetic tool for institutional worksheets."""
import ast
from decimal import Decimal, DecimalException, localcontext
import operator
import re

from .. import access_policy

WHEN = re.compile(r"计算|算一下|算一算|合计|加起来|总价|均价|折算|人均|运算|\b(?:calculate|compute|total cost|work out|sum up)\b", re.I)
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class Arithmetic:
    name = "calculate_amount"
    description = "复核院内金额、数量、比例等简单算式。提供由十进制数、括号和四则运算组成的表达式。"

    def function(self):
        return {"type":"function","function":{"name":self.name,"description":self.description,"parameters":{
            "type":"object","properties":{"expression":{"type":"string","maxLength":192}},
            "required":["expression"],"additionalProperties":False}}}

    def execute(self, args):
        value = args.get("expression") if isinstance(args, dict) and set(args) == {"expression"} else None
        if not isinstance(value,str) or not re.fullmatch(r"[0-9. ()+*/-]{1,192}",value):
            raise ValueError("请仅提交四则运算")
        try:
            expression = value.strip()
            tree = ast.parse(expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 64:
                raise ValueError("请缩短算式")
            def evaluate(node):
                if isinstance(node,ast.Constant) and type(node.value) in (int,float):
                    term = Decimal(ast.get_source_segment(expression,node))
                elif isinstance(node,ast.BinOp) and type(node.op) in OPS:
                    term = OPS[type(node.op)](evaluate(node.left),evaluate(node.right))
                elif isinstance(node,ast.UnaryOp) and type(node.op) in (ast.UAdd,ast.USub):
                    term = evaluate(node.operand)
                    if isinstance(node.op,ast.USub):
                        term = -term
                else:
                    raise ValueError("只支持四则运算")
                if not term.is_finite() or abs(term) > Decimal("1E24"):
                    raise ValueError("数值超出范围")
                return term
            with localcontext() as precision:
                precision.prec = 30
                result = evaluate(tree.body)
            return {"value":format(result,"f")}
        except (DecimalException, SyntaxError, ZeroDivisionError) as err:
            raise ValueError("请重新核对四则算式") from err


def tools_for(user):
    return (Arithmetic(),) if user["kind"] in {"owner","staff"} and access_policy.has(user,"assistants") else ()
