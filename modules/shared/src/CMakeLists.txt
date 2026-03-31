# Service Host — shared C++ library for the generic orchestration host.
add_library(service_host STATIC
    service_host.cpp
)

target_include_directories(service_host PUBLIC
    ${CMAKE_SOURCE_DIR}/modules/shared/include
)

target_link_libraries(service_host PUBLIC
    medtech_types
    RTIConnextDDS::cpp2_api
    RTIConnextDDS::messaging_cpp2_api
)

install(TARGETS service_host ARCHIVE DESTINATION lib)
