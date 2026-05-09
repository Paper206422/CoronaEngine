# CoronaResource Tests

This directory contains unit tests for the CoronaResource library.

## Prerequisites

- CMake 4.0 or higher
- C++20 compatible compiler
- No external test framework required (uses simple built-in test macros)

## Building Tests

To build and run the tests, configure CMake with the `CORONA_RESOURCE_BUILD_TESTS` option enabled:

```bash
cmake -B build -DCORONA_RESOURCE_BUILD_TESTS=ON
cmake --build build
```

## Running Tests

After building, run the tests using CTest:

```bash
cd build
ctest --output-on-failure
```

Or run the test executable directly:

```bash
# Windows
.\build\tests\Debug\corona_resource_tests.exe

# Linux/macOS
./build/tests/corona_resource_tests
```

## Test Coverage

The test suite covers the following areas:

### Basic Functionality
- Loader registration and unregistration
- Basic resource loading
- Typed resource loading
- Error handling (nonexistent types, failed loads)

### Caching
- Cache hit/miss behavior
- `load_once()` bypassing cache
- `contains()` checks
- Cache clearing

### Asynchronous Loading
- Future-based async loading
- Callback-based async loading
- `load_once_async()` variants
- Preloading multiple resources

### Concurrency
- Thread-safe concurrent loading of same resource
- Thread-safe concurrent loading of different resources
- Multiple async loads
- Proper synchronization

### Edge Cases
- Null loader registration
- Multiple loaders for same type
- Wait with no pending tasks
- Singleton instance verification

## Test Structure

- **MockResource**: Simple resource implementation for testing
- **MockLoader**: Configurable loader that supports delays and load counting
- **FailingLoader**: Loader that always fails, for error testing
- **ResourceManagerTest**: Main test fixture with setup/teardown

## Adding New Tests

To add new tests:

1. Add test cases to `test_resource_manager.cpp` or create new test files
2. If creating new files, add them to `CMakeLists.txt`:
   ```cmake
   add_executable(corona_resource_tests
       test_resource_manager.cpp
       your_new_test.cpp  # Add here
   )
   ```

## Notes

- Tests automatically clean up resources in teardown
- Concurrent tests verify thread safety of the ResourceManager
- Mock loaders can simulate loading delays for timing-sensitive tests
