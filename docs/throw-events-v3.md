# 投掷事件识别第三版：先验证现有正面与侧面样本

更新日期：2026-10-12。v3 是独立事件分析版本；v2 源码和输出保留。此次只分析固定机位正面与侧面样本，不把手持视频计入事件结果。Setup 只作为环境参考。

## 本轮修改

v2 在侧面四个事件上全部返回 `uncertain`。v3 保留原始连续帧检测与轨迹输入，增加三种可审查的事件证据：

- **狗相对位置携带线索**：比较飞盘在狗框中的相对位置，允许狗弯身或转向导致狗框中心变化。它支持接盘候选，但没有定位嘴部。
- **接触后检测中断线索**：要求飞盘先沿移动轨迹接近并与狗框相交，有多帧模型观测，随后飞盘模型观测停止、狗仍持续被观测。输出仍为接盘候选，不能单凭消失确认接盘。
- **落地后拾取线索**：飞盘在画面较低区域持续下降后，狗接近最后观测位置，形成 `ground_pickup_candidate`。本样本的正面第 2 次符合这组时空关系，但对应运行没有直接观测到落地帧，所以仍标为候选。

各视频分别运行；两视角汇总按事件顺序配对，不假设它们的时间戳同步。只有两段录像的事件数量和顺序相同时才进行汇总。若两个角度对同一事件给出冲突结果，汇总保留 `uncertain`。

## 当前 sample 结果

| 事件 | 正面 | 侧面 | 两视角汇总 | 人工核对 |
|---|---|---|---|---|
| 1 | 接盘候选 | 接盘候选 | 接盘候选 | 空中接住 |
| 2 | 落地后拾取候选 | 不确定，盘子离开画面 | 落地后拾取候选 | 落地后捡起 |
| 3 | 接盘候选 | 接盘候选 | 接盘候选 | 空中接住 |
| 4 | 不确定 | 接盘候选 | 接盘候选 | 空中接住 |

对你确认的侧面四条标签，按事件顺序汇总后为 4/4 匹配。单看侧面输出则是 3/4 匹配、覆盖 3/4；第二次因飞盘出画而保持不确定，正面视角补充了下降与狗抵达最后观测位置的证据。

这是用于规则开发的同一批样本，4/4 不能解释为独立准确率，也没有测出未来视频的泛化能力。`catch_candidate` 和 `ground_pickup_candidate` 都仍是候选标签；尚未确认嘴部咬合，也没有人工逐帧框标。出画片段本身不会被解释成接住或落地。

## 运行现有样本

从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe cv\analyze_throw_events_v3.py `
  --joint-dir outputs\joint-analysis\front-v1 `
  --detections outputs\front_disc_enhanced.jsonl `
  --output-dir outputs\throw-events-v3\front-v1 `
  --preview outputs\joint-previews\Landscape_Tripod_FrontView.mp4

.\.venv\Scripts\python.exe cv\analyze_throw_events_v3.py `
  --joint-dir outputs\joint-analysis\side-v1 `
  --detections outputs\multi-angle-check\side_disc_enhanced.jsonl `
  --output-dir outputs\throw-events-v3\side-v1 `
  --preview outputs\joint-previews\Landscape_Tripod_SideView.mp4

.\.venv\Scripts\python.exe cv\fuse_throw_events_v3.py `
  --root outputs\throw-events-v3 `
  --labels docs\sample-event-ground-truth-20261012.json

Start-Process 'outputs\throw-events-v3\index.html'
```

手工核对标签仅用于事后评估，不会传入事件分类器。评估文件绑定侧面视频的来源哈希；修改标签请复制文件并保留来源信息。v3 每个视频有独立索引、事件证据、逐帧阶段与运行清单；汇总页写入 `fused-results.json`。

现有 108 项回归测试（含统计模块测试）可运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 下一步的样本内检查

1. 打开汇总页检查四个配对是否符合两个视频的实际顺序。
2. 逐个打开接盘候选，检查接触前后原帧和局部图，重点核对侧面 1、3、4。
3. 检查正面第 2 次拾取候选的 12.733–13.083 秒原帧，确认狗抵达飞盘最后位置时的情形。
4. 若发现漏帧或事件配错，修复后重跑这两段现有录像并比较 v2、v3；此阶段不需要更多视频。

两视角顺序配对适用于这组已知同序 sample。生产数据如果角度不同步、漏掉一次投掷或事件数不同，当前融合器会拒绝汇总；需先建立可靠的跨相机事件匹配。没有相机标定时仍只报告画面事件，不计算实际距离、速度或评分。

## 样本事件统计

新增 `cv/build_throw_statistics.py`，从两视角 `fused-results.json` 生成独立统计页和 JSON：

```powershell
.\.venv\Scripts\python.exe cv\build_throw_statistics.py
Start-Process 'outputs\throw-events-v3\statistics-v1\statistics.html'
```

统计结果将空中接盘、落地后捡起、未接住候选与不确定事件分开计数。空中接盘候选率为“空中接盘候选 / 已分类候选”；取回候选率为“（空中接盘候选 + 落地后捡起候选）/ 已分类候选”。不确定项不进入两个比率的分母，并另外显示判定覆盖率。当前 sample 输出为 4 个已分类候选：3 个空中接盘、1 个落地后捡起；覆盖率 100%，空中接盘候选率 75%，取回候选率 100%。

页面明确标为算法候选统计：人工标签不参与统计，结果不代表验证准确率。输出包含输入哈希和清单；再次运行会校验缓存，若输出被手动改动或输入已变化则拒绝覆盖。旧的融合结果页和 v2/v3 事件结果不变。
