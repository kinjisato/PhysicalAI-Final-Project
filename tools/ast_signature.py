"""Python 3.10+ stable AST signature, ignoring locations and empty type parameters.
The frozen runner has no generic type parameters; nonempty ones are never ignored.
"""
import ast,hashlib,json
def canonical(node):
 if isinstance(node,ast.AST):
  result={'_type':type(node).__name__}
  for name,value in ast.iter_fields(node):
   if name=='type_params' and not value:continue
   result[name]=canonical(value)
  return result
 if isinstance(node,list):return [canonical(x) for x in node]
 if isinstance(node,bytes):return {'_bytes_hex':node.hex()}
 if node is Ellipsis:return {'_ellipsis':True}
 return node
def signature(node):return hashlib.sha256(json.dumps(canonical(node),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
