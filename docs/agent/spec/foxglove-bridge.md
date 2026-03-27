# Spec: Foxglove Visualization Bridge

Behavioral specifications for the Foxglove Bridge plugin pipeline — Routing Service Transformation plugin, Routing Service Adapter plugin (WebSocket sink), and Recording Service Storage plugin (MCAP output). All scenarios are V2 scope.

All scenarios assume the Foxglove Bridge plugins (`libmedtech_foxglove_transf.so`, `libfoxglove_ws_adapter.so`, `libmedtech_mcap_storage.so`) are built and installed per [vision/technology.md](../vision/technology.md) and that the Routing Service / Recording Service XML configurations reference the plugins per [vision/data-model.md — Foxglove Bridge Plugins](../vision/data-model.md#foxglove-bridge-plugins).

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| Transformation plugin shared library | `libmedtech_foxglove_transf.so` — one transformation class per Foxglove target type, selected via XML `<property>` |
| Adapter plugin shared library | `libfoxglove_ws_adapter.so` — output-only `AdapterPlugin` → `Connection` → `DynamicDataStreamWriter` (WebSocket sink) |
| Storage plugin shared library | `libmedtech_mcap_storage.so` — `StorageWriter` → `DynamicDataStorageStreamWriter` (MCAP backend) |
| `@key` fields in transformation output | Stripped — Foxglove types carry no `@key` fields; `robot_id`, `camera_id`, etc. are dropped by the transformation |
| Timestamp population | `SampleInfo.source_timestamp` → Foxglove `timestamp` field on every transformed sample |
| V2 Tier 1 routes | `RobotStateToJointStates`, `RobotStateToToolPose`, `RobotFrameTransformToFoxglove`, `CameraFrameToCompressedImage` |
| MCAP storage — required metadata per sample | Reception timestamp, valid-data flag (for Replay compatibility) |
| Live pipeline | Routing Service: DDS input → Transformation → Adapter (WebSocket) → Foxglove Studio |
| Offline pipeline | Recording Service: DDS subscriber → Transformation → Storage (MCAP) → `.mcap` file |
| Concurrent operation | Both pipelines may run simultaneously over the same Procedure domain data |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## Transformation Correctness

### Scenario: RobotState is transformed to foxglove JointStates `@integration` `@foxglove`

**Given** the Transformation plugin is loaded in a Routing Service route with `mapping=joint_states`
**And** a `Surgery::RobotState` sample is published on the Procedure domain with `joints` containing 6 `JointState` entries (named `joint_1`…`joint_6` with known position, velocity, and effort values)
**When** the transformation processes the sample
**Then** the output is a `foxglove::JointStates` sample containing 6 `foxglove::JointState` entries with matching `name`, `position`, `velocity`, and `effort` values
**And** the `timestamp` field is populated from the input sample's `SampleInfo.source_timestamp`
**And** the `robot_id` `@key` field is not present in the output

### Scenario: RobotState is transformed to foxglove PoseInFrame `@integration` `@foxglove`

**Given** the Transformation plugin is loaded in a Routing Service route with `mapping=pose_in_frame`
**And** a `Surgery::RobotState` sample is published with `tool_tip_pose` containing position (1.0, 2.0, 3.0) and orientation quaternion (0.0, 0.0, 0.707, 0.707)
**When** the transformation processes the sample
**Then** the output is a `foxglove::PoseInFrame` sample with `frame_id` set to `"tool_tip"` and `pose` containing the matching position and orientation values
**And** the `timestamp` field is populated from `SampleInfo.source_timestamp`
**And** the `robot_id` `@key` field is not present in the output

### Scenario: RobotFrameTransform is transformed to foxglove FrameTransforms `@integration` `@foxglove`

**Given** the Transformation plugin is loaded in a Routing Service route with `mapping=frame_transforms`
**And** a `Surgery::RobotFrameTransform` sample is published with `transforms` containing 4 `FrameTransformEntry` entries representing the kinematic chain (base→link1→link2→tool_tip)
**When** the transformation processes the sample
**Then** the output is a `foxglove::FrameTransforms` sample containing 4 `foxglove::FrameTransform` entries with matching `parent_frame_id`, `child_frame_id`, and transform values
**And** each entry's `timestamp` field is populated from `SampleInfo.source_timestamp`
**And** the `robot_id` `@key` field is not present in the output

### Scenario: CameraFrame is transformed to foxglove CompressedImage `@integration` `@foxglove`

**Given** the Transformation plugin is loaded in a Routing Service route with `mapping=compressed_image`
**And** the plugin is configured with a camera-to-frame mapping: `camera_id` = `"endoscope_01"` → `frame_id` = `"endoscope_cam"`
**And** an `Imaging::CameraFrame` sample is published with `format` = `JPEG` (enum), `camera_id` = `"endoscope_01"`, and 1024 bytes of image `data`
**And** the sample's `SampleInfo.source_timestamp` = {sec: 1700000000, nanosec: 500000000}
**When** the transformation processes the sample
**Then** the output is a `foxglove::CompressedImage` sample with `data` (1024 bytes, byte-identical)
**And** the `format` field is the string `"jpeg"` (mapped from the `JPEG` enum value)
**And** the `frame_id` field is `"endoscope_cam"` (derived from the `camera_id` → `frame_id` lookup)
**And** the `timestamp` field is {sec: 1700000000, nsec: 500000000} (from `SampleInfo.source_timestamp`)
**And** the `camera_id` `@key` field is not present in the output

---

## Key & Timestamp Handling

### Scenario: Key fields are stripped from transformation output `@unit` `@foxglove`

**Given** a transformation class processing any medtech type that contains `@key` fields (`robot_id` on `RobotState`, `camera_id` on `CameraFrame`)
**When** the transformation produces the output Foxglove type
**Then** no `@key` field from the input appears in the output type
**And** all fields required by the Foxglove schema are present and correctly populated (from payload fields, `SampleInfo` metadata, or configuration lookups)

### Scenario: Timestamp is populated from SampleInfo source_timestamp `@integration` `@foxglove`

**Given** a Routing Service route with the Transformation plugin
**And** a medtech DDS sample is published with `SampleInfo.source_timestamp` = {sec: 1700000000, nanosec: 500000000}
**When** the transformation processes the sample
**Then** the output Foxglove sample's `timestamp` field contains {sec: 1700000000, nsec: 500000000}

---

## Live Visualization (Routing Service)

### Scenario: Routing Service delivers Foxglove-native data to WebSocket adapter `@e2e` `@foxglove` `@routing`

**Given** Routing Service is configured with the Transformation plugin and the WebSocket Adapter plugin
**And** topic routes for `RobotStateToJointStates`, `RobotStateToToolPose`, `RobotFrameTransformToFoxglove`, and `CameraFrameToCompressedImage` are active
**And** the Adapter plugin's `FoxgloveWebSocketConnection` is configured with a valid WebSocket endpoint
**When** publishers on the Procedure domain publish `RobotState`, `RobotFrameTransform`, and `CameraFrame`
**Then** the Adapter plugin's `DynamicDataStreamWriter::write()` receives transformed Foxglove-native DynamicData for each configured route
**And** the data is serialized and forwarded to the Foxglove Studio live WebSocket connection

### Scenario: Routing Service does not bridge unconfigured Procedure topics to Foxglove `@e2e` `@foxglove` `@routing`

**Given** Routing Service is configured with Foxglove Bridge routes for `RobotState`, `RobotFrameTransform`, and `CameraFrame` only
**When** a publisher on the Procedure domain publishes `OperatorInput`, `SafetyInterlock`, `WaveformData`, or `PatientVitals`
**Then** none of these topics reach the Adapter plugin's WebSocket output
**And** Foxglove Studio does not receive data for any unconfigured topic

---

## Offline Recording (Recording Service)

### Scenario: Recording Service writes Foxglove-native samples to MCAP via Storage plugin `@e2e` `@foxglove` `@recording`

**Given** Recording Service is configured with the Transformation plugin and the MCAP Storage plugin
**And** the Storage plugin's `mcap.filename` property is set to a valid output path
**And** Recording Service is subscribing to `RobotState`, `RobotFrameTransform`, and `CameraFrame` on the Procedure domain
**When** publishers produce samples on these topics for 10 seconds
**Then** the Storage plugin's `DynamicDataStorageStreamWriter::store()` receives transformed Foxglove-native DynamicData for each subscribed topic
**And** the resulting `.mcap` file contains channels corresponding to the Foxglove output types (`foxglove::JointStates`, `foxglove::FrameTransforms`, `foxglove::CompressedImage`, `foxglove::PoseInFrame`)
**And** each MCAP message stores the reception timestamp and valid-data flag from `SampleInfo`
**And** the `.mcap` file can be opened in Foxglove Studio for offline visualization

---

## Concurrent Operation

### Scenario: Routing Service and Recording Service operate simultaneously `@e2e` `@foxglove` `@routing` `@recording`

**Given** Routing Service is running with the Transformation + Adapter plugin pipeline (live visualization)
**And** Recording Service is running with the Transformation + Storage plugin pipeline (MCAP recording)
**And** both services subscribe to the same Procedure domain topics
**When** publishers produce `RobotState` and `CameraFrame` samples for 10 seconds
**Then** the Adapter plugin's WebSocket output receives transformed samples in real time
**And** the Storage plugin's MCAP file accumulates transformed samples concurrently
**And** neither pipeline interferes with the other's throughput or correctness
**And** the recorded MCAP data is consistent with the data delivered live over WebSocket

---

## Plugin Loading

### Scenario: Transformation plugin loads in Routing Service XML configuration `@integration` `@foxglove`

**Given** a Routing Service XML configuration that references the Transformation plugin via `<transformation_plugin>` under `<plugin_library>` with `<dll>medtech_foxglove_transf</dll>`
**When** Routing Service starts
**Then** the plugin loads successfully from `libmedtech_foxglove_transf.so`
**And** routes using the plugin can process samples without error

### Scenario: Adapter plugin loads in Routing Service XML configuration `@integration` `@foxglove`

**Given** a Routing Service XML configuration that references the Adapter plugin via `<adapter_plugin>` under `<adapter_library>` with `<dll>foxglove_ws_adapter</dll>`
**And** a `<connection>` element references the adapter with a valid `ws_uri` property
**When** Routing Service starts
**Then** the Adapter plugin loads successfully from `libfoxglove_ws_adapter.so`
**And** the `FoxgloveWebSocketConnection` is created with the configured WebSocket endpoint

### Scenario: Storage plugin loads in Recording Service XML configuration `@integration` `@foxglove` `@recording`

**Given** a Recording Service XML configuration that references the Storage plugin via `<storage_plugin>` under `<plugin_library>` with `<dll>medtech_mcap_storage</dll>`
**And** the `mcap.filename` property is set
**When** Recording Service starts
**Then** the Storage plugin loads successfully from `libmedtech_mcap_storage.so`
**And** per-stream `DynamicDataStorageStreamWriter` instances are created for each subscribed topic
