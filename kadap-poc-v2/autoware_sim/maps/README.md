# Autoware sample maps

C-실용 demo는 Autoware의 sample-map-planning (Kashiwanoha 캠퍼스 맵)을 사용합니다.
크기 때문에 git에 포함하지 않으며, 아래로 다운로드:

```bash
cd kadap-poc-v2/autoware_sim/maps
python3 -m pip install gdown
python3 -m gdown 'https://docs.google.com/uc?id=1499_nsbUbIeturZaDj7jhUownh5fvXHd' -O sample-map-planning.zip
unzip sample-map-planning.zip
```

산출물:
- `sample-map-planning/lanelet2_map.osm` (1.1MB)
- `sample-map-planning/pointcloud_map.pcd` (27MB)
- `sample-map-planning/map_config.yaml`
- `sample-map-planning/map_projector_info.yaml`

라이선스: Autoware Foundation (Apache 2.0)
