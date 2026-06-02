/**
 * Bridge Utility for QWebChannel
 * 封装了与 Python 后端的通信，支持 Promise 调用
 */

export class Bridge {
  static async callCEF(moduleName, methodName, args) {
    const request = {
      function: methodName,
      module: moduleName,
      args: args || [],
    };

    return new Promise((resolve, reject) => {
      try {
        window.cefQuery({
          request: JSON.stringify(request),
          persistent: false,
          onSuccess: (response) => {
            try {
              const jsonResponse = typeof response === 'string' ? JSON.parse(response) : response;
              console.log('CEF Response:', JSON.stringify(jsonResponse, null, 2));
              if (
                jsonResponse &&
                (jsonResponse.success === false ||
                  jsonResponse.status === 'error' ||
                  jsonResponse.type === 'error' ||
                  jsonResponse.error)
              ) {
                reject(new Error(jsonResponse.error || jsonResponse.message || 'Backend error'));
              } else {
                resolve(jsonResponse);
              }
            } catch (e) {
              resolve(response);
            }
          },
          onFailure: (error_code, error_message) => {
            reject(new Error(`CEF Error (${error_code}): ${error_message}`));
          },
        });
      } catch (error) {
        reject(error);
      }
    });
  }
}

// 快捷访问
export const sceneService = {
  createActor: (sceneName, objPath) =>
    Bridge.callCEF('SceneTools', 'create_actor', [sceneName, objPath]),
  removeActor: (sceneName, actorName) =>
    Bridge.callCEF('SceneTools', 'remove_actor', [sceneName, actorName]),
  createScene: (sceneName) => Bridge.callCEF('SceneTools', 'create_scene', [sceneName]),

  cameraMove: (sceneNameOrPayload, position, forward, up, fov) => {
    if (
      typeof sceneNameOrPayload === 'object' &&
      sceneNameOrPayload !== null &&
      !Array.isArray(sceneNameOrPayload)
    ) {
      const payload = sceneNameOrPayload;
      const sceneId =
        payload.scene_id ??
        payload.sceneId ??
        payload.id ??
        payload.scene_name ??
        payload.sceneName;
      const cameraName =
        payload.camera_name ??
        payload.cameraName ??
        payload.active_camera_name ??
        payload.activeCameraName;
      const worldUp = payload.world_up ?? payload.worldUp ?? payload.up;

      return Bridge.callCEF('SceneTools', 'camera_move', [
        {
          schema_version: payload.schema_version ?? 2,
          scene_id: sceneId,
          scene_name: payload.scene_name ?? payload.sceneName ?? sceneId,
          camera_name: cameraName,
          position: payload.position,
          forward: payload.forward,
          world_up: worldUp,
          up: worldUp,
          fov: payload.fov,
        },
      ]);
    }

    return Bridge.callCEF('SceneTools', 'camera_move', [
      sceneNameOrPayload,
      position,
      forward,
      up,
      fov,
    ]);
  },
  sunDirection: (sceneName, enable, direction) =>
    Bridge.callCEF('SceneTools', 'sun_direction', [sceneName, enable, direction]),
  floorGrid: (sceneName, enabled) =>
    Bridge.callCEF('SceneTools', 'floor_grid', [sceneName, enabled]),
  setPhysicsParams: (sceneName, params) =>
    Bridge.callCEF('SceneTools', 'set_physics_params', [
      sceneName,
      params.gravity,
      params.floor_y,
      params.floor_restitution,
      params.fixed_dt,
    ]),
  getPhysicsParams: (sceneName) => Bridge.callCEF('SceneTools', 'get_physics_params', [sceneName]),
  selectScreenshotPath: (sceneName, cameraName) =>
    Bridge.callCEF('SceneTools', 'select_screenshot_path', [sceneName, cameraName]),
  saveScreenshot: (sceneName, path, cameraName) =>
    Bridge.callCEF('SceneTools', 'save_screenshot', [sceneName, path, cameraName]),
  setOutputMode: (sceneName, cameraName, mode) =>
    Bridge.callCEF('SceneTools', 'set_output_mode', [sceneName, cameraName, mode]),
  getOutputMode: (sceneName, cameraName) =>
    Bridge.callCEF('SceneTools', 'get_output_mode', [sceneName, cameraName]),
  isVisionAvailable: () => Bridge.callCEF('SceneTools', 'is_vision_available', []),
  setRenderBackend: (mode) => Bridge.callCEF('SceneTools', 'set_render_backend', [mode]),
  getRenderBackend: () => Bridge.callCEF('SceneTools', 'get_render_backend', []),
  listActorTree: (sceneName) => Bridge.callCEF('SceneTools', 'list_actor_tree', [sceneName]),
  listSceneTree: (sceneName) => Bridge.callCEF('SceneTools', 'list_scene_tree', [sceneName]),
  openSceneActor: (sceneName, actorName) =>
    Bridge.callCEF('SceneTools', 'open_actor', [sceneName, actorName]),
  focusActor: (sceneName, actorName, cameraName) =>
    Bridge.callCEF('SceneTools', 'focus_actor', [sceneName, actorName, cameraName]),

  getScene: (sceneId) => Bridge.callCEF('SceneDatas', 'get_scene', [sceneId]),
  getActor: (sceneId, actorId) => Bridge.callCEF('SceneDatas', 'get_actor', [sceneId, actorId]),
  actorOperation: (scene_name, actor_name, operation, vector) =>
    Bridge.callCEF('SceneDatas', 'actor_operation', [scene_name, actor_name, operation, vector]),
  selectModelFileDialog: (sceneId, actorId, fileType) =>
    Bridge.callCEF('SceneDatas', 'select_model_file', [sceneId, actorId, fileType]),
  setCameraLock: (sceneName, actorName, enabled) =>
    Bridge.callCEF('SceneDatas', 'actor_operation', [sceneName, actorName, 'SetCameraLock', [enabled]]),
  setCameraLockOffset: (sceneName, actorName, offset) =>
    Bridge.callCEF('SceneDatas', 'actor_operation', [sceneName, actorName, 'SetCameraLockOffset', offset]),
  setCameraLockRotation: (sceneName, actorName, rotation) =>
    Bridge.callCEF('SceneDatas', 'actor_operation', [sceneName, actorName, 'SetCameraLockRotation', rotation]),
};

export const projectService = {
  OnInit: () => Bridge.callCEF('MainView', 'on_init', []),
  importResourceFileByDialog: (sceneName, fileType) =>
    Bridge.callCEF('MainView', 'import_resource_file', [sceneName, fileType]),
  sceneSave: (sceneName) => Bridge.callCEF('MainView', 'scene_save', [sceneName]),
  sceneSwitch: (currentName, toName) =>
    Bridge.callCEF('MainView', 'switch_scene', [currentName, toName]),
  createNewScene: (sceneName) => Bridge.callCEF('MainView', 'create_new_scene', [sceneName]),
  removeScene: (scenePath) => Bridge.callCEF('MainView', 'remove_scene', [scenePath]),

  // 菜单数据接口
  getMenuData: () => Bridge.callCEF('MainView', 'get_menu_data', []),
  updateViewToolState: (toolId, enabled) =>
    Bridge.callCEF('MainView', 'update_view_tool_state', [toolId, enabled]),

  runProject: (scenePath) =>
    Bridge.callCEF('MainView', 'run_project', scenePath ? [scenePath] : []),

  setDragRegions: (Path, x, y, w, h) =>
    Bridge.callCEF('CoronaEditor', 'update_drag_regions', [Path, x, y, w, h]),
};

export const appService = {
  addDockWidget: (route_path, pos, width, height, fixed) =>
    Bridge.callCEF('CoronaEditor', 'open_browser', [route_path, pos, width, height, fixed]),
  removeDockWidget: (tool_name) =>
    Bridge.callCEF('CoronaEditor', 'close_browser_for_js', [tool_name]),
  removeDockWidgetByRoute: (route_name) =>
    Bridge.callCEF('CoronaEditor', 'minimize_browser', [route_name]),
  closeProcess: () => Bridge.callCEF('CoronaEditor', 'close_process'),
  callDockFunction: (routename, functionname, args) =>
    Bridge.callCEF('CoronaEditor', 'js_call_func', [routename, functionname, args]),
  start_engine: () => Bridge.callCEF('CoronaEditor', 'start_corona_engine', []),
};

export const aiService = {
  sendMessageToAIStream: (payload) =>
    Bridge.callCEF('AITool', 'send_message_to_ai_stream', [payload]),
  readLocalFileAsBase64: (filePath) =>
    Bridge.callCEF('AITool', 'read_local_file_as_base64', [filePath]),
  generateHint: (elementType, context = {}) =>
    Bridge.callCEF('AITool', 'generate_hint', [elementType, context]),
};

export const aiClient = {
  chatStream: (request) => Bridge.callCEF('AITool', 'ai_rpc', [request]),
  cancelRequest: (requestId) =>
    Bridge.callCEF('AITool', 'ai_rpc', [
      {
        operation: 'request.cancel',
        request_id: requestId,
      },
    ]),
  getRequestStatus: (requestId) =>
    Bridge.callCEF('AITool', 'ai_rpc', [
      {
        operation: 'request.status',
        request_id: requestId,
      },
    ]),
};

export const scriptingService = {
  /**
   * 执行 Blockly 生成的 Python 代码
   * @param {string} code - Python 代码
   * @param {number} mode - 执行模式（0 = 编辑模式）
   * @param {string} sceneName - 目标场景名称（可选）
   * @param {string} actorName - 目标 Actor 名称（可选）
   */
  executePythonCode: (code, mode, sceneName, actorName) =>
    Bridge.callCEF('ScratchTool', 'execute_python_code', [
      code,
      mode ?? 0,
      sceneName ?? '',
      actorName ?? '',
    ]),

  /**
   * 停止当前正在执行的脚本
   */
  stopScriptExecution: () =>
    Bridge.callCEF('ScratchTool', 'stop_script_execution', []),

  /**
   * 查询当前脚本执行状态
   * @returns {Promise<{status: 'running'|'idle'}>}
   */
  getScriptStatus: () =>
    Bridge.callCEF('ScratchTool', 'get_script_status', []),
};

export const projectLauncherService = {
  // 获取默认项目路径
  getDefaultProjectPath: () => Bridge.callCEF('ProjectLauncher', 'get_default_project_path', []),
  // 浏览文件夹
  browseFolder: (default_path) =>
    Bridge.callCEF('ProjectLauncher', 'browse_folder', [default_path]),
  // 浏览并选择项目文件 (.ini)
  openProjectFile: () => Bridge.callCEF('ProjectLauncher', 'open_project_file', []),
  // 创建项目
  createProject: (projectData) =>
    Bridge.callCEF('ProjectLauncher', 'create_project', [projectData]),
  // 打开项目（执行加载逻辑）
  openProject: (projectPath) => Bridge.callCEF('ProjectLauncher', 'open_project', [projectPath]),
  // 设置项目模式 (2D/3D/渲染)
  setProjectMode: (mode, settings) =>
    Bridge.callCEF('ProjectLauncher', 'set_project_mode', [{ mode, settings }]),
  // 获取版本信息
  getAppVersion: () => Bridge.callCEF('ProjectLauncher', 'get_app_version', []),
  // 获取最近项目列表
  getRecentProjects: () => Bridge.callCEF('ProjectLauncher', 'get_recent_projects', []),
};

export const fileService = {
  getProjectInfo: () => Bridge.callCEF('FileManager', 'get_project_info', []),
  getFiles: (relPath) => Bridge.callCEF('FileManager', 'get_files', [relPath]),
  getFileTree: (relPath) => Bridge.callCEF('FileManager', 'get_file_tree', [relPath]),
  createFolder: (path, folderName) =>
    Bridge.callCEF('FileManager', 'create_folder', [path, folderName]),
  createFile: (path, fileName, type) =>
    Bridge.callCEF('FileManager', 'create_file', [path, fileName, type]),
  deleteItem: (path) => Bridge.callCEF('FileManager', 'delete_item', [path]),
  renameItem: (oldPath, newName) =>
    Bridge.callCEF('FileManager', 'rename_item', [oldPath, newName]),
  openFile: (filePath, fileType) =>
    Bridge.callCEF('FileManager', 'open_file', [filePath, fileType]),
};

export const logService = {
  // 对应 Python 中的 LogTool.set_log_ready
  setLogReady: () => Bridge.callCEF('LogTool', 'set_log_ready', []),
  // 如果需要，也可以添加关闭接口
  setLogClose: () => Bridge.callCEF('LogTool', 'set_log_close', []),
};

export const projectSettingsService = {
  // 获取当前激活项目的配置
  getActiveProjectInfo: () => Bridge.callCEF('ProjectSettings', 'get_active_project_info', []),
  // 保存当前激活项目的配置
  saveActiveProjectInfo: (settings) =>
    Bridge.callCEF('ProjectSettings', 'save_active_project_info', [settings]),
  // 浏览当前项目中的场景文件
  browseSceneFile: () => Bridge.callCEF('ProjectSettings', 'browse_scene_file', []),
};
