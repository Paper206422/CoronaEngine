include_guard(GLOBAL)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(
    $<$<CXX_COMPILER_ID:MSVC>:/source-charset:utf-8>
    $<$<CXX_COMPILER_ID:MSVC>:/execution-charset:utf-8>
)

add_compile_definitions(
    NOMINMAX
    _CRT_SECURE_NO_WARNINGS
)