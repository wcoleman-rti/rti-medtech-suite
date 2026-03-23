# Interfaces — IDL type definitions and code generation

include(ConnextDdsCodegen)

set(IDL_DIR "${CMAKE_CURRENT_SOURCE_DIR}/idl")
set(CPP_GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated/cpp")
set(PY_GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated/python")

# --- IDL modules to process ---
set(IDL_MODULES common surgery monitoring imaging devices clinical_alerts hospital)

# --- C++ code generation ---
foreach(mod ${IDL_MODULES})
    connextdds_rtiddsgen_run(
        IDL_FILE "${IDL_DIR}/${mod}/${mod}.idl"
        LANG "C++11"
        OUTPUT_DIRECTORY "${CPP_GEN_DIR}/${mod}"
        INCLUDE_DIRS "${IDL_DIR}"
        VAR "${mod}_cpp"
        EXTRA_ARGS -standard IDL4_CPP
    )
endforeach()

# Aggregate all generated C++ sources
set(ALL_CPP_SOURCES "")
set(ALL_CPP_HEADERS "")
foreach(mod ${IDL_MODULES})
    list(APPEND ALL_CPP_SOURCES ${${mod}_cpp_CXX11_SOURCES})
    list(APPEND ALL_CPP_HEADERS ${${mod}_cpp_CXX11_HEADERS})
endforeach()

# Create a shared library target from all generated types
add_library(medtech_types ${ALL_CPP_SOURCES} ${ALL_CPP_HEADERS})
target_include_directories(medtech_types PUBLIC
    $<BUILD_INTERFACE:${CPP_GEN_DIR}>
    $<INSTALL_INTERFACE:include>
)
target_link_libraries(medtech_types PUBLIC RTIConnextDDS::cpp2_api)

install(TARGETS medtech_types
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)
install(DIRECTORY "${CPP_GEN_DIR}/" DESTINATION include
    FILES_MATCHING PATTERN "*.hpp")

# --- Python code generation ---
# All Python IDL outputs go into a single flat directory.
# -noSysPathGeneration suppresses rtiddsgen's default sys.path.append
# stanzas in generated code, allowing clean imports via PYTHONPATH.
set(ALL_PY_SOURCES "")
foreach(mod ${IDL_MODULES})
    connextdds_rtiddsgen_run(
        IDL_FILE "${IDL_DIR}/${mod}/${mod}.idl"
        LANG "Python"
        OUTPUT_DIRECTORY "${PY_GEN_DIR}"
        INCLUDE_DIRS "${IDL_DIR}"
        VAR "${mod}_py"
        EXTRA_ARGS -noSysPathGeneration
    )
    list(APPEND ALL_PY_SOURCES ${${mod}_py_PYTHON_SOURCES})
endforeach()

# Custom target to drive Python codegen (otherwise outputs are orphaned)
add_custom_target(medtech_types_python ALL DEPENDS ${ALL_PY_SOURCES})

# Install generated Python modules as flat .py files
install(DIRECTORY "${PY_GEN_DIR}/"
    DESTINATION lib/python/site-packages
    FILES_MATCHING PATTERN "*.py"
    PATTERN "*_timestamp.cmake" EXCLUDE
)
