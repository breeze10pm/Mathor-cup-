# 竞赛支撑材料预览

这里仅保存适合在GitHub上快速查看的轻量派生表格和图，不包含赛题原始数据、DEM、影像、GDB/SHP、第三方栅格或模型文件。

## 内容

- `results/question1/`：第一问探索性前五特征及主对照图。
- `results/question2/`：A/B源区参考点的空间一致性筛查表；不是触发概率。
- `results/question3/`：新报告的转化时间窗、代表时刻和起报回溯指标；不估计触发时间概率或95%置信区间。
- `results/question4/`：中心线到达情景、转化时段的恒速位置参考、口岸附近分段冲淤数据和路线图。路线速度由单一用户报告事件锚定，±15%只是敏感性设定。

运行分析脚本后，在项目根目录运行：

```console
python scripts/package_support_materials.py
```

外部派生数据图表遵循其来源许可。第四问地形和变化产品来源于geo-pera发布版，标注CC BY-NC 4.0；署名为“derived from WorldView-3 © Vantor, open data”及geo-pera/bhotekoshi-2026-reconstruction。赛题附件范围数据只作为空间解译参考；详见`docs/new-evidence-review.md`。
