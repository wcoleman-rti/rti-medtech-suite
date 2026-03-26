add_executable(test_qos_loading test_qos_loading.cpp)
target_link_libraries(test_qos_loading
    PRIVATE
        GTest::gtest_main
        RTIConnextDDS::cpp2_api
)

# Register with CTest
add_test(NAME qos_loading COMMAND test_qos_loading)

# Ensure NDDS_QOS_PROFILES points to source-tree XML in dependency order.
# Use ENVIRONMENT_MODIFICATION with path_list_prepend so CMake doesn't
# interpret the semicolons as list separators.
set(_QOS_DIR "${CMAKE_SOURCE_DIR}/interfaces/qos")
set(_DOM_DIR "${CMAKE_SOURCE_DIR}/interfaces/domains")
set(_PAR_DIR "${CMAKE_SOURCE_DIR}/interfaces/participants")
set_tests_properties(qos_loading PROPERTIES
    ENVIRONMENT_MODIFICATION
        "NDDS_QOS_PROFILES=set:${_QOS_DIR}/Snippets.xml\;${_QOS_DIR}/Patterns.xml\;${_QOS_DIR}/Topics.xml\;${_QOS_DIR}/transport/Default.xml\;${_QOS_DIR}/Participants.xml\;${_DOM_DIR}/Domains.xml\;${_PAR_DIR}/SurgicalParticipants.xml;MEDTECH_APP_NAME=set:test_qos_loading;PARTITION=set:"
)

# --- Robot controller state machine unit tests ---
add_executable(test_robot_controller test_robot_controller.cpp
    ${CMAKE_SOURCE_DIR}/modules/surgical-procedure/robot_controller/robot_controller.cpp
)
target_include_directories(test_robot_controller PRIVATE
    ${CMAKE_SOURCE_DIR}/modules/surgical-procedure/robot_controller
)
target_link_libraries(test_robot_controller
    PRIVATE
        GTest::gtest_main
        medtech_types
        RTIConnextDDS::cpp2_api
)
add_test(NAME robot_controller COMMAND test_robot_controller)

# --- app_names entity name constants tests ---
add_executable(test_app_names test_app_names.cpp)
target_link_libraries(test_app_names
    PRIVATE
        GTest::gtest_main
        medtech_types
        RTIConnextDDS::cpp2_api
)
add_test(NAME app_names COMMAND test_app_names)
