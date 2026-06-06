"""
Terrain Generation Workflow — 常量、预设与 LLM prompt
"""
from __future__ import annotations

TERRAIN_GENERATE_FUNCTION_ID = 21005

DEFAULT_RESOLUTION = 256
DEFAULT_WORLD_SIZE = [2048.0, 2048.0]

ANALYZER_SYSTEM_PROMPT = """你是地形学与自然地理专家。根据用户对自然场景的描述, 输出严格的地形生成参数 JSON。

## 你需要输出的 JSON 结构:
{
  "scene_name": "简短场景名 (≤10字)",
  "terrain": {
    "height_range": [最低海拔m, 最高海拔m],
    "noise_layers": [
      {"frequency": 0.0003, "amplitude": 120, "octaves": 4, "lacunarity": 2.0, "persistence": 0.5}
    ],
    "seed": 随机种子整数
  },
  "ground": [
    {"name": "材质名", "weight": 占比权重, "height_zone": [0.0, 1.0], "slope_range": [0, 45], "color": [R,G,B]}
  ],
  "vegetation": [
    {"name": "植被名", "density": 每平米密度, "slope_max": 最大坡度, "material_mask": ["允许的材质名"]}
  ]
}

## 参数指南:
- height_range: 草原 100-350m, 沙漠 300-800m, 高山 1000-3000m, 平原 0-50m
- noise frequency: 世界坐标(米) × freq = Perlin 特征数. 2048m×0.005≈10个大特征
  * 0.001-0.003: 极平坦 (2-6个大起伏)
  * 0.005-0.015: 中等 (10-30个起伏)
  * 0.02-0.05: 丰富细节 (40-100个起伏)
- octaves: 2=极简单, 4=中等细节, 6-8=丰富细节
- amplitude: 该层噪声对高度(米)的贡献幅度
- ground weight 总和应为 100
- height_zone: [0,1] 归一化, 0=最低点, 1=最高点
- slope_range: 坡度角(度), 越宽越容易分配到该材质
- vegetation density: 草地 0.5-0.9, 灌木 0.02-0.1, 树木 0.001-0.1
- color: 该材质的 RGB 色 (用于 splatmap 可视化)

## 典型场景参考:

### 草原 (Grassland)
height_range: [100, 350]
noise: freq 0.005/amp 120/octaves 4 + freq 0.025/amp 20/octaves 3
ground: 低地草40% + 中坡草30% + 高地草15% + 裸土10% + 岩石5%
slope_range 宽松, 大部分 0-40°

### 沙漠 (Desert)
height_range: [350, 750]
noise: freq 0.002/amp 200/octaves 2 + freq 0.008/amp 35/octaves 3
ground: 平沙40% + 沙丘25% + 碎石20% + 干土10% + 岩石5%
slope 沙丘集中在 3-30°

## 输出规则:
1. 只输出 JSON, 不要 markdown code fences
2. 所有数值要有地理学依据
3. 如果用户描述包含季节/天气, 调整颜色 (秋季草原→金黄调)
4. 如果用户说"简单"或"demo", 降低 resolution 相关参数"""

PRESET_GRASSLAND = {
    "scene_name": "草原",
    "terrain": {
        "height_range": [100, 350],
        "noise_layers": [
            {"frequency": 0.005, "amplitude": 120, "octaves": 4, "lacunarity": 2.0, "persistence": 0.5},
            {"frequency": 0.025, "amplitude": 20, "octaves": 3, "lacunarity": 2.5, "persistence": 0.35},
        ],
        "seed": 42,
    },
    "ground": [
        {"name": "grass_low", "weight": 40, "height_zone": [0.0, 0.55], "slope_range": [0, 30], "color": [95, 170, 65]},
        {"name": "grass_mid", "weight": 30, "height_zone": [0.2, 0.8], "slope_range": [0, 35], "color": [110, 160, 70]},
        {"name": "grass_high", "weight": 15, "height_zone": [0.5, 1.0], "slope_range": [0, 40], "color": [140, 145, 60]},
        {"name": "soil", "weight": 10, "height_zone": [0.0, 0.9], "slope_range": [5, 50], "color": [145, 120, 80]},
        {"name": "rock", "weight": 5, "height_zone": [0.4, 1.0], "slope_range": [15, 60], "color": [130, 125, 120]},
    ],
    "vegetation": [
        {"name": "short_grass", "density": 0.9, "slope_max": 25, "material_mask": ["grass_low", "grass_mid"]},
        {"name": "tall_grass", "density": 0.55, "slope_max": 20, "material_mask": ["grass_low", "grass_mid"]},
        {"name": "shrub", "density": 0.03, "slope_max": 35, "material_mask": ["grass_mid", "grass_high", "soil"]},
        {"name": "flower_patch", "density": 0.04, "slope_max": 15, "material_mask": ["grass_low"]},
    ],
    "water": None,
}

PRESET_DESERT = {
    "scene_name": "沙漠",
    "terrain": {
        "height_range": [350, 750],
        "noise_layers": [
            {"frequency": 0.002, "amplitude": 200, "octaves": 2, "lacunarity": 2.0, "persistence": 0.4},
            {"frequency": 0.008, "amplitude": 35, "octaves": 3, "lacunarity": 2.0, "persistence": 0.3},
        ],
        "seed": 137,
    },
    "ground": [
        {"name": "sand_flat", "weight": 40, "height_zone": [0.0, 0.7], "slope_range": [0, 15], "color": [215, 185, 140]},
        {"name": "sand_dune", "weight": 25, "height_zone": [0.2, 1.0], "slope_range": [3, 30], "color": [230, 200, 155]},
        {"name": "gravel", "weight": 20, "height_zone": [0.0, 0.8], "slope_range": [0, 25], "color": [175, 165, 150]},
        {"name": "soil_dry", "weight": 10, "height_zone": [0.0, 0.5], "slope_range": [0, 20], "color": [160, 140, 110]},
        {"name": "rock", "weight": 5, "height_zone": [0.4, 1.0], "slope_range": [10, 50], "color": [145, 135, 125]},
    ],
    "vegetation": [
        {"name": "dry_grass", "density": 0.015, "slope_max": 10, "material_mask": ["soil_dry"]},
        {"name": "shrub_dry", "density": 0.008, "slope_max": 15, "material_mask": ["soil_dry", "gravel"]},
        {"name": "cactus_small", "density": 0.003, "slope_max": 8, "material_mask": ["sand_flat", "gravel"]},
    ],
    "water": None,
}
