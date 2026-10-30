"""Scene facts are taken from the frozen geometry and confirmed against ROS."""
import json
from storage import ROOT,digest
UNKNOWN=['赤','紫','白','黒','ピンク','オレンジ','茶色','灰色','銀色','金色','水色']
def frozen():
 data=json.loads((ROOT/'config/scene.json').read_text())
 if digest(data['targets'])!=data['layout_sha256']:raise ValueError('Frozen scene checksum mismatch')
 return data
def metadata():
 scene=frozen();targets=scene['targets']
 aliases={'A':['A','青','青色','ブルー'],'B':['B','黄','黄色','イエロー'],'C':['C','緑','緑色','グリーン']}
 for keys,words in [(sorted(targets,key=lambda k:targets[k]['center_base_m'][1]),[['右','右側'],['中央','真ん中','真中'],['左','左側']]),(sorted(targets,key=lambda k:targets[k]['center_base_m'][2]),[['低い','低い対象','低所'],['中間の高さ','中間高さ'],['高い','高い対象','高所']]),(sorted(targets,key=lambda k:targets[k]['horizontal_distance_m']),[['近い','近い対象','一番近い','最も近い','近距離'],['中距離'],['遠い','遠い対象','一番遠い','最も遠い','最遠','遠距離']])]:
  for key,values in zip(keys,words):aliases[key].extend(values)
 return {'layout_sha256':scene['layout_sha256'],'max_visits':10,'objects':{k:{'aliases':aliases[k],'center_base_m':targets[k]['center_base_m'],'height_m':targets[k]['center_base_m'][2],'distance_m':targets[k]['horizontal_distance_m'],'rgba':targets[k]['rgba']} for k in 'ABC'},'unknown_colours':UNKNOWN}
