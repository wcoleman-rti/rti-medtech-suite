cmake_minimum_required(VERSION 3.16)
project(medtech-suite LANGUAGES CXX)

# --- Connext version and architecture (single source of truth) ---
set(CONNEXT_VERSION "7.6.0" CACHE STRING "RTI Connext DDS version")
set(CONNEXTDDS_ARCH "$ENV{CONNEXTDDS_ARCH}" CACHE STRING "RTI Connext target architecture")
if(NOT CONNEXTDDS_ARCH)
    set(CONNEXTDDS_ARCH "x64Linux4gcc8.5.0" CACHE STRING "" FORCE)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
    set_property(CACHE CMAKE_INSTALL_PREFIX
        PROPERTY VALUE "${CMAKE_CURRENT_SOURCE_DIR}/install")
endif()

option(BUILD_SHARED_LIBS "Build shared libraries" ON)

# --- RTI CMake Utilities ---
include(FetchContent)
FetchContent_Declare(
    rticonnextdds-cmake-utils
    GIT_REPOSITORY https://github.com/rticommunity/rticonnextdds-cmake-utils.git
    GIT_TAG        main
)
FetchContent_MakeAvailable(rticonnextdds-cmake-utils)

list(APPEND CMAKE_MODULE_PATH
    "${rticonnextdds-cmake-utils_SOURCE_DIR}/cmake/Modules")

# --- Find RTI Connext DDS ---
find_package(RTIConnextDDS "${CONNEXT_VERSION}" REQUIRED)

# --- Google Test for C++ tests ---
include(CTest)
if(BUILD_TESTING)
    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG        v1.14.0
    )
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

# --- Subdirectories ---
add_subdirectory(interfaces)
if(BUILD_TESTING)
    add_subdirectory(tests/qos)
    add_subdirectory(tests/logging)
endif()

# --- Generate setup.bash ---
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/setup.bash.in"
    "${CMAKE_CURRENT_BINARY_DIR}/setup.bash"
    @ONLY
)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/setup.bash" DESTINATION .)

# --- Install QoS and domain XML ---
install(FILES
    interfaces/qos/Snippets.xml
    interfaces/qos/Patterns.xml
    interfaces/qos/Topics.xml
    interfaces/qos/Participants.xml
    DESTINATION share/qos
)
install(FILES
    interfaces/domains/Domains.xml
    DESTINATION share/domains
)

# --- Resources (fonts, images, stylesheets) ---
add_subdirectory(resources)

# --- Install shared Python packages ---
install(DIRECTORY modules/shared/medtech_gui/
    DESTINATION lib/python/site-packages/medtech_gui
    FILES_MATCHING PATTERN "*.py")
install(DIRECTORY modules/shared/medtech_logging/
    DESTINATION lib/python/site-packages/medtech_logging
    FILES_MATCHING PATTERN "*.py")

# --- Install shared C++ headers ---
install(DIRECTORY modules/shared/medtech_logging/include/
    DESTINATION include
    FILES_MATCHING PATTERN "*.hpp")
