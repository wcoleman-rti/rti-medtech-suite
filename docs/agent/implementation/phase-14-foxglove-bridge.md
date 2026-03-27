# Phase 14: Foxglove Visualization Bridge

**Goal:** Deliver the full Foxglove Studio integration pipeline — Transformation plugin, WebSocket Adapter plugin, MCAP Storage plugin — and verify all `@foxglove` spec scenarios from `spec/foxglove-bridge.md`.

**Depends on:** Phase 6 (Recording & Replay + Foxglove Data Model Alignment — provides the Foxglove-aligned medtech IDL types that the transformation plugin consumes)
**Blocks:** Nothing (terminal V2 phase — can run in parallel with Phases 6–12)

---

## Step 13.1 — Vendor Foxglove IDL Schemas & CMake Codegen

**Work:** Vendor selected Foxglove OMG IDL schemas into the project and wire `rtiddsgen` compilation into the CMake build.

1. Copy the following IDL files from the [foxglove-sdk repository](https://github.com/foxglove/foxglove-sdk/tree/main/schemas/omgidl/foxglove) into `interfaces/idl/foxglove/` at a pinned commit: `Time.idl`, `Quaternion.idl`, `Vector3.idl`, `Pose.idl`, `PoseInFrame.idl`, `JointState.idl`, `JointStates.idl`, `FrameTransform.idl`, `FrameTransforms.idl`, `CompressedImage.idl`
2. Record the pinned commit hash and license in `THIRD_PARTY_NOTICES.md`
3. Add a `interfaces/idl/foxglove/CMakeLists.txt` that invokes `connextdds_rtiddsgen_run()` for C++11 code generation (language `C++11`, standard `IDL4_CPP`). Generated output goes to the build tree.
4. The generated Foxglove C++ types are consumed only by the transformation plugin — they must NOT be registered on any application-domain participant.

**Test gate:**
- [ ] `cmake --build` compiles all 10 vendored Foxglove IDL files without errors
- [ ] Generated C++ headers are present in the build tree under `generated/cpp/foxglove/`
- [ ] No Foxglove types are registered in any domain XML or application participant configuration

---

## Step 13.2 — Transformation Plugin (`libmedtech_foxglove_transf.so`)

**Work:** Implement the Routing Service Transformation plugin that reshapes medtech DDS types into Foxglove-native types as specified in [vision/data-model.md — Foxglove Bridge Plugins](../vision/data-model.md#foxglove-bridge-plugins).

1. Create `services/foxglove-bridge/src/transformation/` directory
2. Implement `MedtechToFoxgloveTransformationPlugin` inheriting from `rti::routing::transf::DynamicDataTransformation`
3. Implement one transformation class per mapping, selected via the `mapping` XML property:
   - `ToJointStates` — `Surgery::RobotState` → `foxglove::JointStates`
   - `ToPoseInFrame` — `Surgery::RobotState` → `foxglove::PoseInFrame`
   - `ToFrameTransforms` — `Surgery::RobotFrameTransform` → `foxglove::FrameTransforms`
   - `ToCompressedImage` — `Imaging::CameraFrame` → `foxglove::CompressedImage`
4. Use `rti::core::xtypes::convert<T>()` for type-safe field mapping
5. Populate `timestamp` from `SampleInfo.source_timestamp` on all transformed outputs
6. Strip all `@key` fields (`robot_id`, `camera_id`) — they must not appear in output
7. Export the plugin entry point via `RTI_TRANSFORMATION_PLUGIN_CREATE_FUNCTION_DEF(MedtechToFoxglovePlugin)`
8. Build as `libmedtech_foxglove_transf.so` and install to `install/lib/`

**Test gate (spec: foxglove-bridge.md — Transformation Correctness, Key & Timestamp Handling):**
- [ ] `RobotState` → `foxglove::JointStates`: 6 joint entries with matching name/position/velocity/effort
- [ ] `RobotState` → `foxglove::PoseInFrame`: tool_tip_pose extracted, `frame_id` = `"tool_tip"`
- [ ] `RobotFrameTransform` → `foxglove::FrameTransforms`: 4 kinematic chain entries with matching parent/child frame IDs
- [ ] `CameraFrame` → `foxglove::CompressedImage`: byte-identical `data`, matching `format`/`frame_id`
- [ ] No `@key` fields present in any output type
- [ ] `timestamp` populated from `SampleInfo.source_timestamp` on all outputs
- [ ] Plugin loads successfully in a Routing Service XML configuration

---

## Step 13.3 — WebSocket Adapter Plugin (`libfoxglove_ws_adapter.so`)

**Work:** Implement the Routing Service Adapter plugin that serializes transformed Foxglove DynamicData to a Foxglove Studio live WebSocket connection.

1. Create `services/foxglove-bridge/src/adapter/` directory
2. Implement the three-class hierarchy per the Routing Service Adapter API:
   - `FoxgloveWebSocketAdapter` (`rti::routing::adapter::AdapterPlugin`) — top-level factory
   - `FoxgloveWebSocketConnection` (`rti::routing::adapter::Connection`) — owns shared WebSocket connection state, creates stream writers
   - `FoxgloveWebSocketStreamWriter` (`rti::routing::adapter::DynamicDataStreamWriter`) — serializes post-transformation Foxglove DynamicData and sends over WebSocket
3. Output-only adapter — input-side methods return `nullptr`
4. Connection-level property: `ws_uri` (WebSocket endpoint)
5. Per-output property: `channel` (Foxglove channel name mapping)
6. Map `StreamInfo` metadata to Foxglove channel/schema advertisement
7. Export via `RTI_ADAPTER_PLUGIN_CREATE_FUNCTION_DEF(FoxgloveWebSocketAdapter)`
8. Build as `libfoxglove_ws_adapter.so` and install to `install/lib/`

**Test gate (spec: foxglove-bridge.md — Live Visualization, Plugin Loading):**
- [ ] Adapter plugin loads in Routing Service XML configuration
- [ ] `FoxgloveWebSocketConnection` created with configured `ws_uri`
- [ ] `DynamicDataStreamWriter::write()` receives transformed Foxglove-native DynamicData
- [ ] Unconfigured Procedure topics do NOT reach the WebSocket output
- [ ] Plugin serializes and forwards data to Foxglove Studio WebSocket connection

---

## Step 13.4 — MCAP Storage Plugin (`libmedtech_mcap_storage.so`)

**Work:** Implement the Recording Service Storage plugin that writes transformed Foxglove-native samples to MCAP files.

1. Create `services/foxglove-bridge/src/storage/` directory
2. Implement the storage hierarchy per the Recording Service Storage API:
   - `McapStorageWriter` (`rti::recording::storage::StorageWriter`) — opens MCAP file, creates per-stream writers
   - `McapDynamicDataWriter` (`rti::recording::storage::DynamicDataStorageStreamWriter`) — receives post-transformation Foxglove DynamicData + `SampleInfo`, writes MCAP records
3. Map each DDS stream to an MCAP channel/schema pair via `StreamInfo`
4. Store reception timestamp and valid-data flag from `SampleInfo` for Replay compatibility
5. Plugin property: `mcap.filename` (output file path)
6. Export via `RTI_RECORDING_STORAGE_WRITER_CREATE_DEF(McapStorageWriter)`
7. Build as `libmedtech_mcap_storage.so` and install to `install/lib/`

**Test gate (spec: foxglove-bridge.md — Offline Recording, Plugin Loading):**
- [ ] Storage plugin loads in Recording Service XML configuration
- [ ] Per-stream `DynamicDataStorageStreamWriter` instances created for each subscribed topic
- [ ] `.mcap` file contains channels for `foxglove::JointStates`, `foxglove::FrameTransforms`, `foxglove::CompressedImage`, `foxglove::PoseInFrame`
- [ ] Each MCAP message stores reception timestamp and valid-data flag
- [ ] `.mcap` file can be opened in Foxglove Studio for offline visualization

---

## Step 13.5 — Routing Service Foxglove Bridge Configuration

**Work:** Author the Routing Service XML configuration that wires the Transformation plugin and Adapter plugin together for live Foxglove Studio visualization.

1. Create `services/foxglove-bridge/config/routing_service_foxglove.xml`
2. Register the Transformation plugin under `<plugin_library>` with `<transformation_plugin>`
3. Register the Adapter plugin under `<adapter_library>` with `<adapter_plugin>`
4. Define a `<connection>` for the WebSocket adapter with configurable `ws_uri`
5. Define topic routes for all V2 Tier 1 mappings:
   - `RobotStateToJointStates`
   - `RobotStateToToolPose`
   - `RobotFrameTransformToFoxglove`
   - `CameraFrameToCompressedImage`
6. Each route reads from the DDS input, applies the transformation, and writes to the adapter output
7. This configuration follows the XML pattern documented in [vision/data-model.md — Routing Service XML Pattern (V2)](../vision/data-model.md#routing-service-xml-pattern-v2)

**Test gate (spec: foxglove-bridge.md — Live Visualization):**
- [ ] Routing Service starts with the configuration without errors
- [ ] All 4 topic routes active and processing samples
- [ ] Transformed Foxglove-native data reaches the Adapter plugin's WebSocket output

---

## Step 13.6 — Recording Service MCAP Configuration

**Work:** Author the Recording Service XML configuration that wires the Transformation plugin and Storage plugin together for offline MCAP recording.

1. Create `services/foxglove-bridge/config/recording_service_mcap.xml`
2. Register the Storage plugin under `<plugin_library>` with `<storage_plugin>`
3. Register the Transformation plugin (same shared library as Step 13.2)
4. Configure Recording Service to subscribe to Procedure domain topics (`RobotState`, `RobotFrameTransform`, `CameraFrame`)
5. Apply the Transformation plugin before the Storage plugin — transformed samples reach `store()`
6. Set `mcap.filename` property for output path
7. This configuration follows the XML pattern documented in [vision/data-model.md — Recording Service XML Pattern (V2)](../vision/data-model.md#recording-service-xml-pattern-v2)

**Test gate (spec: foxglove-bridge.md — Offline Recording):**
- [ ] Recording Service starts with the configuration without errors
- [ ] 10 seconds of recording produces a valid `.mcap` file
- [ ] MCAP file contains Foxglove-native channels for all configured topics

---

## Step 13.7 — Concurrent Operation & Integration Test

**Work:** Verify that both pipelines (live Routing Service + offline Recording Service) operate simultaneously without interference, and run the full `@foxglove` spec scenario suite.

1. Start both Routing Service (live bridge) and Recording Service (MCAP recorder) against the same Procedure domain
2. Run all surgical procedure simulators for a 30-second capture window
3. Verify live WebSocket output and MCAP file are consistent

**Test gate (spec: foxglove-bridge.md — Concurrent Operation, all scenarios):**
- [ ] Both services run concurrently without errors
- [ ] Adapter plugin receives transformed samples in real time
- [ ] MCAP file accumulates transformed samples concurrently
- [ ] Neither pipeline interferes with the other's throughput or correctness
- [ ] All 13 `@foxglove` spec scenarios pass

---

## Step 13.8 — Docker Integration & README

**Work:** Add Foxglove Bridge containers to the Docker Compose environment and document the service.

1. Create `docker/foxglove-bridge.Dockerfile` using the C++ runtime base image
2. Install all three plugin shared libraries into the container image
3. Add `foxglove-routing-service` and `foxglove-recording-service` services to `docker-compose.yml` (behind a `foxglove` profile)
4. Write `services/foxglove-bridge/README.md` following the documentation standard from `spec/documentation.md`

**Test gate:**
- [ ] `docker compose --profile foxglove up` starts both Foxglove Bridge services alongside the existing surgical procedure stack
- [ ] `services/foxglove-bridge/README.md` passes markdownlint and section-order lint
- [ ] All `@foxglove` tests pass in the Docker Compose environment

---

## Step 13.9 — Performance Baseline Recording

**Work:** Record the Phase 14 performance baseline covering the Foxglove Bridge pipeline.

1. Run the performance benchmark harness with Foxglove Bridge services active
2. Measure transformation latency overhead (time added by the transformation pipeline per sample)
3. Measure WebSocket adapter throughput (samples/sec delivered to the WS endpoint)
4. Measure MCAP storage throughput (samples/sec written to disk)
5. Commit baseline to `tests/performance/baselines/`

**Test gate:**
- [ ] Performance benchmark completes without exceeding defined thresholds
- [ ] Baseline file committed to `tests/performance/baselines/`
- [ ] Transformation overhead does not cause deadline violations on bridged topics
