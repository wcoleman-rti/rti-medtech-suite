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
set_tests_properties(qos_loading PROPERTIES
    ENVIRONMENT_MODIFICATION
        "NDDS_QOS_PROFILES=set:${_QOS_DIR}/Snippets.xml\;${_QOS_DIR}/Patterns.xml\;${_QOS_DIR}/Topics.xml\;${_QOS_DIR}/Participants.xml\;${_DOM_DIR}/domains.xml"
)
