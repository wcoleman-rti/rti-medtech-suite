# Robot controller — C++ service library + executable
add_library(robot_controller_service STATIC
    robot_controller_service.cpp
    robot_controller.cpp
)

target_include_directories(robot_controller_service PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/include
)

target_link_libraries(robot_controller_service PUBLIC
    medtech_types
    RTIConnextDDS::cpp2_api
)

add_executable(robot-controller
    main.cpp
)

target_include_directories(robot-controller PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/include
)

target_link_libraries(robot-controller PRIVATE
    robot_controller_service
)

install(TARGETS robot_controller_service ARCHIVE DESTINATION lib)
install(TARGETS robot-controller RUNTIME DESTINATION bin)
