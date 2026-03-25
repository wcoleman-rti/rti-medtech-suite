# Robot controller — C++ executable with dual AsyncWaitSet pattern
add_executable(robot-controller
    main.cpp
    robot_controller.cpp
)

target_include_directories(robot-controller PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/modules/shared/medtech_logging/include
)

target_link_libraries(robot-controller PRIVATE
    medtech_types
    RTIConnextDDS::cpp2_api
)

install(TARGETS robot-controller RUNTIME DESTINATION bin)
