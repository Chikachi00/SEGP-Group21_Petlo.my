# 不同角度视频检测验证

三个新增视频完整运行；正面复用上次完整测试。检测算法及源文件未修改。

相同配置：本地 yolo11n.pt，1280 全景，2×2 重叠 20% 的局部区域（960 输入），狗、人和飞盘阈值均为 0.25。

| 拍摄角度 | 完整处理帧 | 有狗框 | 有飞盘框 | 有人框 |
|---|---:|---:|---:|---:|
| 正面固定镜头 | 2200 | 1737 | 1661 | 2200 |
| 侧面固定镜头 | 2163 | 1911 | 2163 | 2163 |
| 竖屏手持 | 179 | 95 | 106 | 78 |
| Setup 环境参考 | 1198 | 264 | 744 | 639 |

以上是检测存在计数，不是准确率或召回率。多个飞盘会同时出现；需区分手持、空中、狗嘴边、地面飞盘。

## 人工抽查

按源帧编号提取带框回放，查看少量原尺寸画面和局部图。样本有意覆盖不同时间及疑似问题，不能据此估算总体准确率。

### 侧面固定镜头

固定侧面有可用的空中飞盘与近处狗检测，但远处狗会与 person 混淆，还存在手腕误检、裁剪边界重复框和狗嘴边飞盘漏检。每帧有盘主要包含手持/地面目标，不能宣称空中飞盘检测达到 100%。

- [0.000 秒，源帧 0](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_01_full.jpg)：近处狗、人和手持飞盘有正确框；右下角边缘白色物体也被框为飞盘，属于需要核查的疑似误检，暂不计为已确认错误。
- [3.003 秒，源帧 180](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_02_full.jpg)：空中浅色飞盘、狗及手持粉色飞盘正确检测；能看到同一画面中的多个不同飞盘。
- [11.995 秒，源帧 719](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_03_full.jpg)：左侧空中飞盘、狗、手持飞盘与地面飞盘都有框；整帧有盘不是单独空中目标的持续识别指标。
- [21.071 秒，源帧 1263](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_04_full.jpg)：近处狗与手持浅色飞盘正确检测；旁边另一个 disc 框覆盖手腕/前臂，属于误检。
- [26.476 秒，源帧 1587](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_05_full.jpg)：左侧远处狗被标为 person（约 0.35），没有 dog 框；同一个手持粉色飞盘被局部检测输出完整框与截断框，仍有重复框。
- [30.380 秒，源帧 1821](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_06_full.jpg)：近处狗与手持粉色飞盘有正确框，同时包含多个静止地面飞盘。
- [36.069 秒，源帧 2162](../outputs/multi-angle-check/samples/Landscape_Tripod_SideView/frame_07_full.jpg)：左侧远处狗及嘴边粉色飞盘被两个 person 框覆盖，没有 dog 框；飞盘检测只框住地面和手持目标，漏掉嘴边粉色飞盘。

完整源帧、真实 PTS、框坐标范围和输出解码帧数均通过验证；源 SHA256 与原资料包一致。处理耗时约 980.0 秒（有并发影响）。

### 竖屏手持

近处画面可用于追踪原型；不能假设手持移动、远处逆光画面与固定正面画面具有相同检测质量。

- [0.000 秒，源帧 0](../outputs/multi-angle-check/samples/Portrait_Handheld/frame_01_full.jpg)：狗、人和手持蓝色飞盘有正确框；全景还显示地面飞盘，不能把所有飞盘框都当成空中目标。
- [1.001 秒，源帧 30](../outputs/multi-angle-check/samples/Portrait_Handheld/frame_02_full.jpg)：狗、人和手持蓝色飞盘有正确框，同时检测到地面飞盘。
- [2.002 秒，源帧 60](../outputs/multi-angle-check/samples/Portrait_Handheld/frame_03_full.jpg)：狗与人有框，但手持蓝色飞盘可见而漏检；这一帧仍有地面飞盘框，整帧有飞盘并不能说明手持目标被识别。
- [3.003 秒，源帧 90](../outputs/multi-angle-check/samples/Portrait_Handheld/frame_04_full.jpg)：镜头转动过程中仍检测到空中蓝色飞盘与狗；狗置信度约 0.38。
- [4.004 秒，源帧 120](../outputs/multi-angle-check/samples/Portrait_Handheld/frame_05_full.jpg)：狗与嘴边蓝色飞盘仍可见，但没有检测结果；目标远离镜头，场景有明显逆光。不能将其简单归为目标离开画面。
- [5.939 秒，源帧 178](../outputs/multi-angle-check/samples/Portrait_Handheld/frame_06_full.jpg)：远处狗与嘴边蓝色飞盘仍可见，但没有检测结果。

完整源帧、真实 PTS、框坐标范围和输出解码帧数均通过验证；源 SHA256 与原资料包一致。处理耗时约 84.7 秒（有并发影响）。

### Setup 环境参考

环境参考运行正常；抽查显示近处狗头和地面飞盘可检测。人框可能对应摄影者局部手臂，不可直接作为投掷者轨迹。Setup 不适合作为投掷或接盘识别的验证样本。

- [0.000 秒，源帧 0](../outputs/multi-angle-check/samples/Setup/frame_01_full.jpg)：画面下沿的近处狗头正确检测；场景包含拍摄设备。
- [13.013 秒，源帧 390](../outputs/multi-angle-check/samples/Setup/frame_02_full.jpg)：这一帧主要为树木与地面，没有检测框；未见明显狗或飞盘，不能将空结果计为漏检。
- [19.987 秒，源帧 599](../outputs/multi-angle-check/samples/Setup/frame_03_full.jpg)：地面蓝色飞盘正确检测；person 框覆盖摄影者伸入画面的手臂和手，不能据此建立投掷者的全身位置或投掷事件。
- [26.994 秒，源帧 809](../outputs/multi-angle-check/samples/Setup/frame_04_full.jpg)：地面蓝色飞盘正确检测，原尺寸局部核对为真实飞盘；该框不是飞行证据。
- [39.940 秒，源帧 1197](../outputs/multi-angle-check/samples/Setup/frame_05_full.jpg)：这一帧主要为天空、树木与场地，没有检测框；不能拿它验证动作检测效果。

完整源帧、真实 PTS、框坐标范围和输出解码帧数均通过验证；源 SHA256 与原资料包一致。处理耗时约 517.0 秒（有并发影响）。

## 结论与后续

不同角度应分别保留验证结果。可以开始追踪原型开发，但应先标注至少几次完整动作，检查远处狗、空中飞盘以及接触狗嘴前后的漏检和误检。Setup 用作环境与背景误检参考，不能作为动作识别效果的证明。
正、侧面是否为同一投掷尚未确认；若为同一动作，后续训练/验证划分应放在同一组。

本地浏览入口：`outputs/multi-angle-check/index.html`；各完整回放、JSONL 和验证结果在同一目录。当前仍没有稳定轨迹 ID、事件识别或人工真值准确率。
