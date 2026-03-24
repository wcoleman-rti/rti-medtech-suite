add_executable(test_init_logging test_init_logging.cpp)
target_link_libraries(test_init_logging
    PRIVATE
        GTest::gtest_main
        RTIConnextDDS::cpp2_api
)
target_include_directories(test_init_logging
    PRIVATE
        ${CMAKE_SOURCE_DIR}/modules/shared/medtech_logging/include
)

add_test(NAME init_logging COMMAND test_init_logging)
