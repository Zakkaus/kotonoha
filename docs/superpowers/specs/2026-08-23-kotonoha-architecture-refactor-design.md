# Kotonoha 高质量架构重构设计规格

**状态：设计草案**
**范围：歌词链路、播放协调、Overlay 展示、平台适配、配置与生命周期**

## 1. 背景与问题定义

最近 40 个提交不是 40 个互不相关的 bug。它们反复触及同一条运行路径：

```text
播放器/网络/文件输入
    -> metadata 清洗与匹配
    -> 歌词 source 选择与请求
    -> lyric document / timing / clock
    -> LyricsState
    -> Overlay / platform surface
```

当前实现已经有 `mpris_track.py`、`match.py`、`resolver.py`、`platform/` 等模块，但这些模块的边界
主要是文件边界，不是责任边界。关键语义仍通过 `Any`、裸 `dict`、字符串 mode、nullable operation
和未集中拥有的 `asyncio.Task` 传递。

因此新目标不是“把大文件拆小”，而是建立能约束后续开发的系统契约：

1. 外部输入只能通过 typed adapter 进入 application/domain。
2. raw data、normalized view、stable identity 不得互相覆盖。
3. domain 只负责规则，不依赖 Qt、aiohttp、D-Bus、filesystem 或 native bridge。
4. application 负责 workflow、generation、task/resource ownership 和 state commit。
5. presentation 只消费 view model、发布 user intent，不执行 provider/platform policy。
6. platform adapter 负责 compositor/toolkit 事实，并报告实际 operation result。
7. 每条用户可见行为都有可执行的契约测试和失败路径测试。

## 2. 设计原则

### 2.1 行为先于实现

重构开始前先建立行为目录。PR 矩阵是事实证据，不是新设计的约束。每个行为都标记为：

- **Retain**：重新确认有用户价值，并纳入新契约的行为；
- **Redefine**：当前行为互相冲突或边界不可证明，需要用新 policy 重新定义；
- **Remove**：偶然出现、没有稳定契约、会增加错误复杂度的行为。

歌词和 Overlay 的 PR 行为矩阵见：

- [歌词 PR 行为矩阵](2026-08-23-lyrics-pr-behavior-matrix.md)
- [Overlay PR 行为矩阵](2026-08-23-overlay-pr-behavior-matrix.md)
- [行为等价性与 corner case 保护](2026-08-23-behavior-equivalence-policy.md)

### 2.2 端口携带语义，adapter 携带不确定性

adapter 内部可以处理第三方动态对象、Qt 对象、D-Bus Variant、HTTP body 和文件 descriptor；
adapter 退出时必须将结果收敛为 domain/application 能理解的结构：

```python
BoundaryResult[T]
    = Accepted(value: T)
    | Miss(reason: MissReason)
    | Rejected(reason: RejectionReason)
    | Unavailable(reason: UnavailableReason)
    | Failed(kind: FailureKind, retryable: bool)
```

不要让调用方通过 `None`、空字符串、`False` 或异常类型猜测这些状态。

### 2.3 生命周期是架构的一部分

每个异步 component 必须有一个 owner：

```text
creator -> retained task/resource handle -> cancel/await -> closed state
```

`asyncio.shield` 只改变 caller cancellation，不改变 owner shutdown 责任。线程池、aiohttp session、
D-Bus bus、WebSocket client、SQLite executor、Qt timer、Layer Shell surface 和 blur object 都必须
有对应的 close/stop/release 语义。

### 2.4 值对象表达业务区别

以下区别不能继续只用 primitive 表达：

| 目前的 primitive | 目标值对象/枚举 | 必须表达的区别 |
| --- | --- | --- |
| `dict[str, Any]` MPRIS metadata | `RawTrackObservation` | 外部原值、采样时间、播放器身份、可能缺失字段 |
| 清洗后的 title | `NormalizedTrackView` | lookup 视图，不覆盖 raw view |
| `str` provider name | `SourceId` / `SourcePlan` | provider identity、顺序、能力、是否 live/cacheable |
| `None` lyric result | `SourceResult` | miss、unavailable、failure、rejected、hit |
| `asyncio.Task` | `OwnedOperation` / workflow task handle | creator、generation、cancel、await、result commit |
| `bool` capability | `Capability[Reason]` | available/unavailable 与可显示原因 |
| `None` input/blur region | `InputPolicy` / `BlurPolicy` | clear、full click-through、specific rectangle |
| `str` Config mode | `Enum` + serializer | 内部合法状态与 JSON 字符串格式分离 |

### 2.5 行为等价性是迁移门禁

当前正则、parser 分支和 corner case 不是可以随意清理的实现噪声；它们已经表达了真实输入的业务边界。
重构必须先建立 typed behavior corpus，并把当前实现作为临时 oracle：

1. corpus 通过公开输入和公开输出投影记录行为，不记录 regex pattern、私有 helper 或调用顺序；
2. 每条规则至少有正向样本和近邻负向样本，组合规则还要覆盖 raw/normalized/gate 的连续路径；
3. 新实现对同一 corpus 执行 canonical comparison，未登记的差异一律视为回归；
4. 有意改变必须用 `BehaviorChangeRecord` 写明 case、旧行为、新目标、影响和替代契约，不能只修改 expected；
5. 旧 oracle 只在新实现成为唯一 publisher、等价 suite 通过且差异登记完成后删除。

等价测试保护的是公共行为，不要求新实现保留旧 regex 或模块形状。详细的 case 模型、比较投影和适用
路径见 [行为等价性与 corner case 保护](2026-08-23-behavior-equivalence-policy.md)。

## 3. 目标分层

```rva-layer-map
{
  "title": "Kotonoha 目标分层架构",
  "status": "candidate",
  "layers": [
    {"id": "layer_presentation", "label": "展示层", "items": ["LyricsOverlay", "SettingsDialog", "Tray", "ViewModel binding"]},
    {"id": "layer_application", "label": "应用编排层", "items": ["PlaybackCoordinator", "LyricsResolutionWorkflow", "OverlayCoordinator", "ApplicationSupervisor"]},
    {"id": "layer_domain", "label": "领域规则层", "items": ["Track identity", "Matching", "Lyric document", "Timeline/display state", "Source policy"]},
    {"id": "layer_ports", "label": "端口与契约层", "items": ["PlayerPort", "LyricsSource", "ClockPort", "SurfacePort", "ConfigStore"]},
    {"id": "layer_infrastructure", "label": "基础设施适配层", "items": ["MPRIS/D-Bus", "HTTP providers", "Cider transport", "Filesystem/SQLite", "Qt/Layer Shell/native"]},
    {"id": "layer_composition", "label": "组合根", "items": ["main.py", "AppController", "dependency wiring", "lifecycle shutdown"]}
  ]
}
```

依赖方向：

```text
composition -> application -> domain
composition -> ports <- infrastructure
composition -> presentation -> ports/application intents
```

domain 不得反向依赖 infrastructure；presentation 不得依赖 provider、resolver、MPRIS、native bridge；
infrastructure 不得决定业务来源顺序、匹配置信度或 HUD 展示状态。

## 4. 目标领域模型

### 4.1 Playback domain

```text
RawTrackObservation
    player_id: PlayerId
    reported_track_id: str | None
    raw_title: str
    raw_artists: tuple[str, ...]
    raw_album: str
    raw_duration_s: float | None
    position_s: float | None
    status: PlaybackStatus
    observed_at: MonotonicTime

TrackIdentity
    player_id
    provider_hint: ProviderHint | None
    raw: RawTrackMetadata
    normalized: NormalizedTrackView
    generation: TrackGeneration
```

`MetadataStabilizer` 是纯 domain service。它只处理 observation 序列，不读取 D-Bus，也不启动网络。
它负责：空 metadata、混合 metadata、稳定窗口、missing artist、identity change 和 generation。

`PlaybackCoordinator` 是 application service。它负责：

- 从 `PlayerPort` 获取 sample；
- 维护 player selection 和当前 identity；
- 在 identity commit 时启动/取消 `LyricsResolutionWorkflow`；
- 将 authoritative clock observation 发布给 timeline；
- 在 generation 检查通过后提交 state。

### 4.2 Lyrics domain

```text
LyricDocument
    source: SourceId
    song_id: ProviderSongId | None
    metadata: CandidateMetadata
    lines: tuple[LyricLine, ...]
    timing: TimingKind
    evidence: MatchEvidence | ExactHintEvidence | LocalFileEvidence

LyricLine
    start: Seconds
    end: Seconds | None
    text: str
    translation: str | None
    words: tuple[LyricWord, ...]

SourcePlan
    stages: tuple[SourceStage, ...]
    policy: ResolutionPolicy

ResolutionDecision
    kind: Hit | Miss | Unavailable | Failed | Rejected
    source: SourceId | None
    reason: ResolutionReason
    document: LyricDocument | None
```

`TitleGrammar` 只输出结构化 title parts、version qualifiers、artist evidence 和 query views；
`Matcher` 只消费这些结构并输出 `MatchEvidence`。matcher 不应导入 titles 的私有 regex helper。

`LyricsSource` 只做一个 source stage：给定 `LyricsRequest`，返回 `SourceResult[LyricDocument]`。
network、Cider、sidecar、embedded 和 exact-id 都可以是 source adapter，但 precedence 由
`SourcePlan` 决定，不由某个 source 在内部偷偷跳过其他 source。

### 4.3 Timeline/display domain

```text
DisplayState
    NoTrack | Resolving | LyricsAvailable | LyricsNotFound

DisplayFrame
    state: DisplayState
    previous: LyricLine | None
    current: LyricLine | None
    next: LyricLine | None
    word_progress: WordProgress | None
    clock_position_s: float | None
    provider_label: str | None
    diagnostic: DisplayDiagnostic | None
```

interlude detection、line selection、word highlight、translation merge、per-track offset 和 pause/resume
都应在 Qt 之外完成。Qt 只把 `DisplayFrame` 映射到 label、animation 和 paint operation。

### 4.4 Overlay/platform domain

```text
SurfaceState = Unprepared | Prepared | Active | Rebinding | Degraded | Closing | Closed
DragState = Idle | Pressed | Updating | Released | Rejected

SurfaceCommand = Prepare | Activate(output) | Rebind(output) | ApplyInput(policy)
                 | ApplyBlur(policy) | Close
SurfaceResult = Applied | NotSupported(reason) | Rejected(reason) | Failed(reason, retryable)
```

`SurfacePort` 不暴露 Qt widget、ctypes pointer 或 compositor name。`PlatformAdapter` 可以使用这些
细节，但必须报告实际结果。output binding、surface release、blur ownership、input region 和 drag
strategy 由 platform lifecycle owner 持有。

## 5. 关键行为契约

### 5.1 歌词请求

1. 一个 committed `TrackIdentity` 产生一个 generation。
2. generation 变化立即取消仍属于前一身份的 workflow；过期结果不能更新 LyricsState、Cider gate 或 cache。
3. `SourcePlan` 明确 exact hint、local file、Cider、network provider 的顺序。
4. `prefer_best_lyrics` 必须成为显式 `ResolutionPolicy`：
   - `ordered_first`：按配置顺序逐 stage；第一个满足最低置信度的结果结束；
   - `best_confidence`：只并发仍可能胜出的 stage，结果按 confidence 再按配置顺序决定；
   - 两种 policy 都有每 source deadline 和整体 generation owner。
5. source 结果必须区分 `Miss`、`Unavailable`、`Failed`、`Rejected`；只有 `Miss` 可进入 negative memory cache。
6. 只有通过持久化置信度门槛的 artifact 才写 SQLite；cache hit 必须重新检查 schema/normalizer version。
7. Cider 被选中后绑定 client id；Cider 是否为外部歌词提供 clock calibration 由显式 ClockPolicy 决定，
   Cider 断线或 Position 不可用时保留已找到的歌词并回退 MPRIS。

### 5.2 时间轴与展示

1. parser 输出的 line/word timing 必须经过统一 invariant validator：非负、单调、有界、文本与 word 可对应。
2. `karaoke=False` 时展示 line text，不计算 word highlight；`karaoke=True` 但 word timing 不可用时退化到 line timing。
3. 当前行、transition 和 interlude 是 DisplayFrame/Timeline 的内容；resolution state 只表达
   `NoTrack`、`Resolving`、`LyricsAvailable` 和 `LyricsNotFound`，不能用空字符串表达“正在查找”或“找不到歌词”。
4. per-track offset 以 stable `TrackIdentity` key 关联，由 application/config service 持有；Overlay 只发布 intent。
5. pause/resume 使用 clock policy 选择 player position 或估算值；clock policy 不由 renderer 决定。
6. font fit 使用实际 layout measurement，不能用固定字符数替代最终渲染尺寸。

### 5.3 Surface/platform

1. surface 只有在 `Active` 才能接收 input/blur/move command。
2. output rebinding 是资源迁移：释放旧 surface 相关资源、创建新 surface、确认应用结果，再更新 active output。
3. rebinding 失败保留 pending intent，不能清除后让 overlay 永久隐藏。
4. deferred callback 到达 `Closing/Closed` 只能丢弃或记录，不能访问 QWidget/native handle。
5. capability reason 与 operation result 必须可供 Settings/Overlay 展示；不支持不是成功 no-op。
6. drag update 失败时 release 不得保存未发生的几何；strategy 只负责平台位移，application 负责持久化。

### 5.4 新设计的默认 policy（提案）

以下是为了让实现可以从明确边界开始的初始提案，不是从当前代码自动推导出的兼容承诺。Phase 0 必须
逐项确认；若作者修改，必须同时更新 SourcePlan、DisplayState 和对应的 golden scenario。

1. **来源优先级**：用户确认歌词 -> 同一音频的 sidecar -> embedded artifact -> 可信 provider hint
   -> 已选 Cider session -> 按配置顺序的 network search。自动 cache 是每个 source 的存储加速，不是独立的
   来源，也不能改变来源优先级；用户确认结果才是最高优先级的本地歌词。
2. **默认竞争策略**：默认使用 `ordered_first`，保证请求数量、结果选择和失败诊断可预测；`best_confidence`
   只能作为显式配置，且必须有总预算、取消规则和确定性的 tie-breaker。
3. **置信度处理**：`EXACT/HIGH` 才能成为自动 active document；`MEDIUM` 等待其他来源后只作为 fallback，
   不写自动持久 cache；`LOW` 直接 `Rejected`。用户确认后可以保存任意候选为本地歌词。
4. **播放状态**：没有可提交曲目身份时输出 `NoTrack`；身份已提交但尚未完成解析时输出 `Resolving`；解析完成
   但没有可接受文档时输出 `LyricsNotFound`。界面文案使用“找不到歌词”，这些状态不得用空字符串或保留上一曲文本
   来隐式表达。
5. **时钟归属**：`follow_lyrics_source` 使用当前歌词来源的 clock；`prefer_matching_cider` 在 Cider 确认
   同曲且 tick 有效时优先使用 Cider。Cider 失效时保留已找到的歌词并回退 MPRIS，不能由 Overlay 猜测。

## 6. 禁止的依赖和实现形状

- domain/application 不得导入 `PyQt6`、`aiohttp`、`dbus_fast`、`mutagen`、`ctypes` 或直接读取环境变量。
- presentation 不得读取 `XDG_*`、Qt platform name、desktop name 来判断业务 capability。
- provider adapter 不得直接写 `LyricsState`，只能返回 `SourceResult`。
- parser 不得启动 task、读 config、访问 cache 或决定 source precedence。
- 不得新增 `Any` 到 domain/application contract；第三方动态访问只允许集中在 adapter。
- 不得新增 `or default` 处理具有“缺失/空值/零值”区别的业务字段。
- 不得在 QWidget callback、signal handler 或 resolver 内创建无 owner 的 task。
- 不得让一个 PR 同时修改不相关的 lifecycle、parser、UI visual 和 packaging 行为；行为边界不同必须拆 PR。

## 7. 迁移安全线

重构期间现有实现和新实现可以短期并存，但只能有一个 state publisher。每次迁移必须：

1. 先将当前观察到的目标行为加入 typed corpus，并为每条规则补正向/近邻负向 case；
2. 固定现有实现的 canonical public result，作为迁移期间的临时 oracle；
3. 新组件通过 port 接收相同输入，并由 differential comparator 验证相同 domain/application output；
4. 对允许的行为变化提交 `BehaviorChangeRecord` 和新的目标契约，不能直接改 baseline；
5. 切换唯一 publisher，并继续运行等价 suite，直到没有未登记差异；
6. 删除被替代路径、compatibility fallback 和 oracle，并写明删除条件；
7. 运行 domain、application、adapter、Qt offscreen、live session 各层检查。
