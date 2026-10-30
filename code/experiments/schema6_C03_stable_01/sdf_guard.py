"""Read-only Ignition StringMsg/SDF validation; no scene or motion writes."""
import ast,hashlib,json,math,re,subprocess,time,xml.etree.ElementTree as ET
COMMAND=['ign','service','-s','/world/default/generate_world_sdf','--reqtype','ignition.msgs.SdfGeneratorConfig','--reptype','ignition.msgs.StringMsg','--timeout','20000','--req','']
class SDFError(RuntimeError):pass
def decode_validate(stdout,targets):
 if not isinstance(stdout,str) or not stdout.strip():raise SDFError('EMPTY_SDF_RESPONSE')
 envelope=re.fullmatch(r'\s*data\s*:\s*("(?:\\.|[^"\\])*")\s*',stdout,re.S)
 if envelope is None:raise SDFError('INVALID_OR_TRUNCATED_STRINGMSG: expected one quoted data field')
 try:xml=ast.literal_eval(envelope.group(1))
 except (SyntaxError,ValueError) as exc:raise SDFError('INVALID_STRINGMSG_ESCAPE: '+str(exc)) from exc
 if not isinstance(xml,str) or not xml.strip() or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise SDFError('INVALID_SDF_XML_OR_DTD')
 normalization=None;raw_xml=xml
 # Fortress exports this robot include URI as unescaped XML character data.
 # Escape only the known URI token for parsing. ET.text remains identical;
 # no geometry, target or scene is fabricated, changed or sent to Gazebo.
 try:root=ET.fromstring(xml)
 except ET.ParseError as original:
  literal='<uri>file://<urdf-string></uri>'
  if xml.count(literal)!=1:raise SDFError('INVALID_SDF_XML at '+str(original.position)+': '+str(original)) from original
  xml=xml.replace(literal,'<uri>file://&lt;urdf-string&gt;</uri>')
  try:root=ET.fromstring(xml)
  except ET.ParseError as exc:raise SDFError('INVALID_SDF_XML at '+str(exc.position)+': '+str(exc)) from exc
  includes=[x for x in root.findall('./world/include') if x.findtext('uri')=='file://<urdf-string>']
  if len(includes)!=1 or includes[0].findtext('name')!='crane_plus':raise SDFError('UNEXPECTED_UNESCAPED_INCLUDE_URI')
  normalization={'kind':'XML_character_data_escaping_only','uri_text':'file://<urdf-string>','original_parse_position':list(original.position),'raw_xml_sha256':hashlib.sha256(raw_xml.encode()).hexdigest(),'parse_xml_sha256':hashlib.sha256(xml.encode()).hexdigest()}
 worlds=root.findall('world')
 if root.tag!='sdf' or root.get('version')!='1.9' or len(worlds)!=1 or worlds[0].get('name')!='default':raise SDFError('SDF_ROOT_WORLD_VERSION_MISMATCH')
 models=worlds[0].findall('model');names=[m.get('name') for m in models];expected={t['model'] for t in targets.values()}
 if len(names)!=len(set(names)) or set(names)!=expected:raise SDFError('SDF_TARGET_MEMBERSHIP_MISMATCH')
 found={m.get('name'):m for m in models};result={}
 for t in targets.values():
  m=found[t['model']]
  if m.findtext('static')!='true':raise SDFError('SDF_TARGET_NOT_STATIC: '+t['model'])
  links=m.findall('link')
  if len(links)!=1 or len(links[0].findall('collision'))!=1:raise SDFError('SDF_COLLISION_STRUCTURE_MISMATCH')
  collision=links[0].find('collision');geometry=collision.find('geometry')
  if geometry is None or len(list(geometry))!=1 or geometry[0].tag!='box':raise SDFError('SDF_COLLISION_NOT_SINGLE_BOX')
  try:sizes=[float(v) for v in geometry.findtext('box/size','').split()]
  except ValueError as exc:raise SDFError('SDF_INVALID_SIZE') from exc
  if len(sizes)!=3 or any(not math.isfinite(v) or v<=0 for v in sizes) or max(abs(v-w) for v,w in zip(sizes,t['size_m']))>1e-6:raise SDFError('SDF_COLLISION_SIZE_MISMATCH')
  result[t['label']]={'static':True,'collision_size_m':sizes}
 return result,{'expected_format':'Ignition StringMsg text data -> SDF 1.9/default world','actual_format':'validated quoted StringMsg and complete SDF XML','XML_character_data_normalization':normalization,'validated_targets':sorted(expected),'xml_bytes':len(raw_xml.encode())}

class Reader:
 def __init__(self,writer,folder,rpc):self.writer=writer;self.folder=folder;self.rpc=rpc;self.sequence=0
 def verify(self,targets):
  self.sequence+=1;prefix=self.folder/f'sdf_{self.sequence:03d}';started=time.monotonic();record={'status':'FAIL','persistent_client':True,'fresh_acquisition':True,'cache_used':False,'pre_ai':self.rpc.pre_ai}
  try:
   xml,transport=self.rpc.acquire('GET');self.writer.text(str(prefix)+'.stdout',xml);result,details=decode_validate('data: '+json.dumps(xml),targets);record.update(status='PASS',transport=transport,wire_format='StringMsg protobuf JSON from persistent Node',**details);return result
  except Exception as exc:record['error']=type(exc).__name__+': '+str(exc);raise
  finally:record['wall_seconds']=time.monotonic()-started;self.writer.json(str(prefix)+'_result.json',record)
