import json
import math
import subprocess
from pathlib import Path
import msgpack

root = Path(__file__).resolve().parents[1]
def meta(path):
    u=msgpack.Unpacker(raw=False,strict_map_key=False)
    u.feed(path.read_bytes()[8:])
    outer=list(u)
    v=msgpack.Unpacker(raw=False,strict_map_key=False)
    v.feed(outer[0])
    inner=list(v)
    return msgpack.unpackb(inner[4],raw=False,strict_map_key=False)['V2Obj']

rows=[]
print('$ du -sk volumes/disk*')
print(subprocess.check_output(['du','-sk',*[str(root/f'volumes/disk{i}') for i in range(1,5)]],text=True).replace(str(root)+'/', ''),end='')
for i in range(1,5):
    d=root/f'volumes/disk{i}'
    files=[f for f in d.rglob('*') if f.is_file()]
    apparent=sum(f.stat().st_size for f in files)
    allocated=sum(f.stat().st_blocks*512 for f in files)
    path=d/'hw2/it_vacancy_data.csv/xl.meta'
    m=meta(path)
    part=next(path.parent.rglob('part.1'))
    row={'disk':i,'apparent_file_bytes':apparent,'allocated_file_bytes':allocated,
         'part_bytes':part.stat().st_size,'meta_bytes':path.stat().st_size,
         'data_shards':m['EcM'],'parity_shards':m['EcN'],'index':m['EcIndex'],
         'distribution':m['EcDist'],'block_size':m['EcBSize'],'object_size':m['Size'],
         'json_meta_bytes':{f.name:(d/'hw2'/f.name/'xl.meta').stat().st_size for f in (root/'dataset').glob('vacancy*.json')}}
    rows.append(row)
    print(f"disk{i}: files={apparent} B; allocated files={allocated} B; CSV part.1={part.stat().st_size} B")
    print(f"  xl.meta: data={m['EcM']} parity={m['EcN']} block={m['EcBSize']} index={m['EcIndex']} distribution={m['EcDist']}")
size=rows[0]['object_size']; block=rows[0]['block_size']
full,last=divmod(size,block); chunks=math.ceil(size/block)
shard=full*math.ceil(block/2)+math.ceil(last/2)
on_disk=shard+32*chunks
assert all(r['part_bytes']==on_disk for r in rows)
print(f'CSV: {full} full blocks + {last} B; logical shard={shard} B; checksums={32*chunks} B; part.1={on_disk} B')
(root/'evidence/measurements.json').write_text(json.dumps(rows,indent=2))
