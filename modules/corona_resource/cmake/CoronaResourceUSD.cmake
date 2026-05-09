# Internal function: Recursively find all dependencies of a USD module
# Parameters:
#   MODULE_NAME - Name of the module
#   OUTPUT_VAR - Output variable name (stores all dependencies)
#   VISITED_VAR - List of visited modules (to avoid circular dependencies)
function(_corona_get_usd_dependencies MODULE_NAME OUTPUT_VAR VISITED_VAR)
    # Get the visited list
    set(_visited ${${VISITED_VAR}})

    # If already visited, return directly
    if ("${MODULE_NAME}" IN_LIST _visited)
        return()
    endif ()

    # Mark as visited
    list(APPEND _visited "${MODULE_NAME}")
    set(${VISITED_VAR} ${_visited} PARENT_SCOPE)

    # Check if target exists
    if (NOT TARGET ${MODULE_NAME})
        return()
    endif ()

    # Get the current result list
    set(_result ${${OUTPUT_VAR}})
    list(APPEND _result "${MODULE_NAME}")

    # Get the target's link libraries
    get_target_property(_link_libs ${MODULE_NAME} LINK_LIBRARIES)

    if (_link_libs AND NOT _link_libs STREQUAL "_link_libs-NOTFOUND")
        foreach (_lib ${_link_libs})
            # Filter out system and external libraries
            if (TARGET ${_lib} AND NOT _lib MATCHES "^(TBB::|Boost::|ZLIB::|OpenGL::)")
                # Recursively find dependencies
                _corona_get_usd_dependencies(${_lib} _result _visited)
            endif ()
        endforeach ()
    endif ()

    # Get interface link libraries
    get_target_property(_interface_libs ${MODULE_NAME} INTERFACE_LINK_LIBRARIES)

    if (_interface_libs AND NOT _interface_libs STREQUAL "_interface_libs-NOTFOUND")
        foreach (_lib ${_interface_libs})
            if (TARGET ${_lib} AND NOT _lib MATCHES "^(TBB::|Boost::|ZLIB::|OpenGL::)")
                _corona_get_usd_dependencies(${_lib} _result _visited)
            endif ()
        endforeach ()
    endif ()

    # Return result
    set(${OUTPUT_VAR} ${_result} PARENT_SCOPE)
    set(${VISITED_VAR} ${_visited} PARENT_SCOPE)
endfunction()

# Function: Configure and link specified USD components to target
# Parameters:
#   TARGET_NAME - Name of the target to link USD to
#   USD_COMPONENTS - List of required USD components (e.g., usdGeom usdShade)
function(corona_link_usd TARGET_NAME)
    # Parse variadic arguments as USD component list
    set(USD_COMPONENTS ${ARGN})

    if (NOT USD_COMPONENTS)
        message(FATAL_ERROR "corona_link_usd: Must specify at least one USD component")
    endif ()

    # Check if target exists
    if (NOT TARGET ${TARGET_NAME})
        message(FATAL_ERROR "corona_link_usd: Target '${TARGET_NAME}' does not exist")
    endif ()

    # Verify and link each USD component
    set(_linked_libs)
    foreach (_component ${USD_COMPONENTS})
        if (NOT TARGET ${_component})
            message(WARNING "corona_link_usd: USD component '${_component}' not found, skipping")
            continue()
        endif ()

        list(APPEND _linked_libs ${_component})
        message(STATUS "corona_link_usd: Linking ${_component} to ${TARGET_NAME}")
    endforeach ()

    # Link to target
    if (_linked_libs)
        target_link_libraries(${TARGET_NAME} PRIVATE ${_linked_libs})

        # Add USD include directories
        get_target_property(_usd_include_dirs ${_linked_libs} INTERFACE_INCLUDE_DIRECTORIES)
        if (_usd_include_dirs)
            target_include_directories(${TARGET_NAME} PRIVATE ${_usd_include_dirs})
        endif ()
    else ()
        message(FATAL_ERROR "corona_link_usd: No valid USD components were linked")
    endif ()
endfunction()

# Function: Setup USD plugin files (plugInfo.json and schema files)
# Parameters:
#   USD_COMPONENTS - List of USD components (used to determine dependencies)
# Notes:
#   This function sets up the necessary variables for corona_copy_usd to use
#   DLL files are handled separately via corona_copy_runtime_files
function(corona_install_usd)
    set(USD_COMPONENTS ${ARGN})

    if (NOT USD_COMPONENTS)
        message(FATAL_ERROR "corona_install_usd: Must specify at least one USD component")
    endif ()

    # Get OpenUSD directories
    FetchContent_GetProperties(OpenUSD)

    if (NOT openusd_POPULATED)
        message(WARNING "corona_install_usd: OpenUSD not populated, skipping")
        return()
    endif ()

    # Store paths in cache for corona_copy_usd to use
    set(CORONA_USD_BUILD_DIR "${openusd_BINARY_DIR}" CACHE INTERNAL "OpenUSD build directory")
    set(CORONA_USD_SOURCE_DIR "${openusd_SOURCE_DIR}" CACHE INTERNAL "OpenUSD source directory")

    message(STATUS "corona_install_usd: OpenUSD build directory = ${CORONA_USD_BUILD_DIR}")
    message(STATUS "corona_install_usd: OpenUSD source directory = ${CORONA_USD_SOURCE_DIR}")
endfunction()

# Function: Copy USD plugin files directly to target's runtime directory
# Parameters:
#   TARGET_NAME - Name of the target that needs USD plugin files
# Notes:
#   Copies plugInfo.json and generatedSchema.usda directly from USD build/source
#   to target's runtime directory, eliminating the intermediate install step
function(corona_copy_usd TARGET_NAME)
    if (NOT TARGET ${TARGET_NAME})
        message(FATAL_ERROR "corona_copy_usd: Target '${TARGET_NAME}' does not exist")
    endif ()

    if (NOT DEFINED CORONA_USD_BUILD_DIR OR NOT DEFINED CORONA_USD_SOURCE_DIR)
        message(WARNING "corona_copy_usd: USD paths not set, call corona_install_usd first")
        return()
    endif ()

    # Create copy script that runs at build time
    set(_copy_script "${CMAKE_CURRENT_BINARY_DIR}/copy_usd_${TARGET_NAME}.cmake")
    file(WRITE "${_copy_script}" "
# ============================================================================
# USD Plugin File Copy Script (Simplified)
# Copies directly from USD build/source to target runtime directory
# ============================================================================

set(_usd_build_dir \"\${USD_BUILD_DIR}\")
set(_usd_source_dir \"\${USD_SOURCE_DIR}\")
set(_dest_dir \"\${DEST_DIR}\")
set(_stamp_file \"\${DEST_DIR}/usd/.corona_usd_stamp\")

# Check if USD directories exist
if(NOT EXISTS \"\${_usd_build_dir}\")
    message(WARNING \"[USD Copy] Build directory not found: \${_usd_build_dir}\")
    return()
endif()

# Check if update is needed
set(_need_update TRUE)
if(EXISTS \"\${_stamp_file}\")
    file(GLOB_RECURSE _pluginfo_files \"\${_usd_build_dir}/pxr/usd/*/plugInfo.json\")
    set(_need_update FALSE)
    foreach(_file \${_pluginfo_files})
        if(\"\${_file}\" IS_NEWER_THAN \"\${_stamp_file}\")
            set(_need_update TRUE)
            break()
        endif()
    endforeach()
endif()

if(NOT _need_update)
    message(STATUS \"[USD Copy] Plugin files up to date, skipping\")
    return()
endif()

message(STATUS \"[USD Copy] Copying USD plugin files to \${_dest_dir}/usd\")

# Create destination directory
file(MAKE_DIRECTORY \"\${_dest_dir}/usd\")

# Copy plugInfo.json files from build directory
file(GLOB_RECURSE _pluginfo_files \"\${_usd_build_dir}/pxr/usd/*/plugInfo.json\")
foreach(_pluginfo \${_pluginfo_files})
    file(RELATIVE_PATH _rel_path \"\${_usd_build_dir}/pxr/usd\" \"\${_pluginfo}\")
    get_filename_component(_module_name \"\${_rel_path}\" DIRECTORY)
    set(_dest_file \"\${_dest_dir}/usd/\${_module_name}/resources/plugInfo.json\")
    get_filename_component(_dest_subdir \"\${_dest_file}\" DIRECTORY)
    file(MAKE_DIRECTORY \"\${_dest_subdir}\")
    file(COPY \"\${_pluginfo}\" DESTINATION \"\${_dest_subdir}\")
endforeach()

# Copy generatedSchema.usda files from source directory
file(GLOB_RECURSE _schema_files \"\${_usd_source_dir}/pxr/usd/*/generatedSchema.usda\")
foreach(_schema \${_schema_files})
    if(NOT \"\${_schema}\" MATCHES \"testenv\")
        file(RELATIVE_PATH _rel_path \"\${_usd_source_dir}/pxr/usd\" \"\${_schema}\")
        get_filename_component(_module_name \"\${_rel_path}\" DIRECTORY)
        set(_dest_file \"\${_dest_dir}/usd/\${_module_name}/resources/generatedSchema.usda\")
        get_filename_component(_dest_subdir \"\${_dest_file}\" DIRECTORY)
        file(MAKE_DIRECTORY \"\${_dest_subdir}\")
        file(COPY \"\${_schema}\" DESTINATION \"\${_dest_subdir}\")
    endif()
endforeach()

# Create top-level plugInfo.json index
set(_top_pluginfo \"\${_dest_dir}/usd/plugInfo.json\")
file(WRITE \"\${_top_pluginfo}\" \"{\\n    \\\"Includes\\\": [ \\\"*/resources/\\\" ]\\n}\\n\")

# Update timestamp
file(MAKE_DIRECTORY \"\${_dest_dir}/usd\")
string(TIMESTAMP _ts \"%Y-%m-%d %H:%M:%S\")
file(WRITE \"\${_stamp_file}\" \"Updated: \${_ts}\")

message(STATUS \"[USD Copy] Complete\")
")

    # Add POST_BUILD command
    add_custom_command(TARGET ${TARGET_NAME} POST_BUILD
            COMMAND ${CMAKE_COMMAND}
                -DUSD_BUILD_DIR=${CORONA_USD_BUILD_DIR}
                -DUSD_SOURCE_DIR=${CORONA_USD_SOURCE_DIR}
                -DDEST_DIR=$<TARGET_FILE_DIR:${TARGET_NAME}>
                -P "${_copy_script}"
            COMMENT "Copying USD plugin files for ${TARGET_NAME}"
            VERBATIM
    )

    message(STATUS "corona_copy_usd: Configured for ${TARGET_NAME}")
endfunction()

