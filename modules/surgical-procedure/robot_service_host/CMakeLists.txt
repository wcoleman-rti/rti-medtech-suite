# Robot Service Host — header-only factory + executable
add_library(robot_service_host INTERFACE)

target_include_directories(robot_service_host INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/include
    ${CMAKE_SOURCE_DIR}/modules/surgical-procedure/robot_controller
)

target_link_libraries(robot_service_host INTERFACE
    robot_controller_service
    service_host
)

add_executable(robot-service-host
    main.cpp
)

target_include_directories(robot-service-host PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/include
)

target_link_libraries(robot-service-host PRIVATE
    robot_service_host
)

install(TARGETS robot-service-host RUNTIME DESTINATION bin)
