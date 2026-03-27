# Robot Service Host — C++ service host library + executable
add_library(robot_service_host STATIC
    robot_service_host.cpp
)

target_include_directories(robot_service_host PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/medtech_logging/include
    ${CMAKE_SOURCE_DIR}/modules/shared/medtech_dds_init/include
    ${CMAKE_SOURCE_DIR}/modules/surgical-procedure/robot_controller
)

target_link_libraries(robot_service_host PUBLIC
    robot_controller_service
    medtech_types
    RTIConnextDDS::cpp2_api
    RTIConnextDDS::messaging_cpp2_api
)

add_executable(robot-service-host
    main.cpp
)

target_include_directories(robot-service-host PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/medtech_logging/include
    ${CMAKE_SOURCE_DIR}/modules/shared/medtech_dds_init/include
)

target_link_libraries(robot-service-host PRIVATE
    robot_service_host
)

install(TARGETS robot_service_host ARCHIVE DESTINATION lib)
install(TARGETS robot-service-host RUNTIME DESTINATION bin)
