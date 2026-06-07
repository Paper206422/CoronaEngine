<template>
  <div class="rounded-lg overflow-hidden flex flex-col flex-1 min-h-0 w-full relative bg-[#282828]/70">
    <DockTitleBar
      v-if="!isDocked"
      title="场景管理"
      extraClass="bg-[#84A65B] rounded-t-md"
      routePath="/SceneBar"
      @close="CloseFloat"
    />

    <!-- 主内容区域 -->
    <div class="flex flex-col flex-1 min-h-0">
      <div class="flex items-center gap-2 p-2 bg-[#1a1a1a]/50 border-b border-[#333]">
        <div class="text-[10px] text-gray-400 truncate flex-1">
          <span class="text-[#84a65b] font-bold">{{ currentSceneName }}</span>
        </div>
      </div>

      <!-- 资源搜索栏(B-2 竞态保护 + 防抖 + 错误兜底) -->
      <div class="flex items-center gap-1 px-2 py-1.5 bg-[#2a2a2a] border-b border-[#1a1a1a]">
        <div class="relative flex-1">
          <input
            v-model="searchInput"
            type="text"
            placeholder="🔍 搜索资源(名称/中文/拼音,支持模糊)"
            class="w-full pl-2 pr-7 py-1 text-xs bg-[#1e1e1e] text-[#e0e0e0] border border-[#3a3a3a] rounded focus:border-[#84a65b] focus:outline-none"
            :disabled="searchLoading"
            data-testid="resource-search-input"
            @input="onSearchInput"
            @keydown.enter="onSearchEnter"
            @keydown.esc="onSearchClear"
          />
          <button
            v-if="searchInput && !searchLoading"
            class="absolute right-1 top-1/2 -translate-y-1/2 text-[#666] hover:text-[#aaa] text-xs"
            data-testid="resource-search-clear"
            @click="onSearchClear"
          >
            ✕
          </button>
          <span
            v-if="searchLoading"
            class="absolute right-1 top-1/2 -translate-y-1/2 text-[#84a65b] text-[10px] animate-pulse"
          >
            ⌛
          </span>
        </div>
        <!-- 以图搜索 -->
        <label
          class="px-1.5 py-1 text-xs bg-[#3c3c3c] hover:bg-[#545454] rounded text-[#e0e0e0] cursor-pointer flex items-center"
          :class="{ 'opacity-50 pointer-events-none': searchLoading }"
          title="以图搜索(本地 pHash)"
          data-testid="resource-image-search"
        >
          🖼
          <input
            ref="imageInputRef"
            type="file"
            accept="image/*"
            class="hidden"
            @change="onImageSelected"
          />
        </label>
        <!-- 重建索引 -->
        <button
          class="px-1.5 py-1 text-xs bg-[#3c3c3c] hover:bg-[#545454] rounded text-[#e0e0e0]"
          :class="{ 'opacity-50 pointer-events-none': searchLoading }"
          title="重建索引"
          data-testid="resource-rebuild"
          @click="onRebuildIndex"
        >
          🔄
        </button>
      </div>

      <!-- 搜索结果区(可切换) -->
      <div
        v-if="searchActive"
        class="flex-1 overflow-y-auto bg-[#282828]/50"
        data-testid="resource-search-results"
      >
        <!-- 错误提示 -->
        <div
          v-if="searchError"
          class="m-2 p-2 text-xs text-red-300 bg-red-900/30 border border-red-700/50 rounded"
          data-testid="resource-search-error"
        >
          ⚠ {{ searchError }}
        </div>
        <!-- 命中计数 -->
        <div v-else class="px-2 py-1 text-[10px] text-[#909090] border-b border-[#1a1a1a]/30">
          找到 <span class="text-[#84a65b] font-bold">{{ searchResults.length }}</span> 项
          <span v-if="searchLastQuery" class="ml-2">query=“{{ searchLastQuery }}”</span>
          <span v-if="searchElapsedMs" class="ml-2 text-[#666]">{{ searchElapsedMs }}ms</span>
        </div>
        <!-- 命中列表 -->
        <div
          v-for="item in searchResults"
          :key="item.path"
          class="group flex items-center px-2 py-1 hover:bg-[#3c3c3c]/50 cursor-pointer border-l-2 border-transparent hover:border-[#84a65b] text-xs"
          :class="{ 'bg-[#264f78]/60': selectedItem === 'search:' + item.path }"
          data-testid="resource-search-item"
          @click="selectedItem = 'search:' + item.path"
          @dblclick="OnLocateSearchItem(item)"
        >
          <span class="w-5 flex-shrink-0 text-center">
            <span :class="typeColorClass(item.type)">{{ typeIcon(item.type) }}</span>
          </span>
          <span class="text-[#e0e0e0] truncate flex-1 ml-1" :title="item.name">
            {{ item.name }}
          </span>
          <span class="text-[10px] text-[#666] mr-1">
            {{ item.type_label }}
          </span>
          <span
            v-if="item.score != null"
            class="text-[10px] text-[#84a65b] mr-1"
            :title="'相似度'"
          >
            {{ Math.round(item.score * 100) }}%
          </span>
          <button
            class="w-5 h-5 flex items-center justify-center text-[#666] hover:text-[#84a65b] rounded opacity-0 group-hover:opacity-100"
            title="定位到资源"
            @click.stop="OnLocateSearchItem(item)"
          >
            ◎
          </button>
        </div>
        <div
          v-if="!searchError && searchResults.length === 0"
          class="px-4 py-8 text-center text-[#666] text-xs"
        >
          暂无匹配结果
        </div>
      </div>

      <!-- 原场景树(无搜索时显示) -->
      <div v-show="!searchActive" class="flex flex-col flex-1 min-h-0">
        <div class="flex items-center gap-2 p-2 bg-[#1a1a1a]/50 border-b border-[#333]"></div>

      <!-- 工具栏 -->
      <div class="flex items-center gap-1 px-2 py-1.5 bg-[#3c3c3c]/60 border-b border-[#1a1a1a]/30">
        <!-- 导入下拉 -->
        <div class="relative">
          <button
            class="p-1.5 hover:bg-[#545454] rounded text-[#e0e0e0] text-xs flex items-center gap-1"
            title="导入"
            @click.stop="ToggleModelDropdown"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 4v16m8-8H4"
              ></path>
            </svg>
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M19 9l-7 7-7-7"
              ></path>
            </svg>
          </button>
          <div
            v-if="ShowModelDropdown"
            v-click-outside="CloseModelDropdown"
            class="absolute z-20 mt-1 w-32 bg-[#3c3c3c] rounded shadow-lg border border-[#1a1a1a]"
          >
            <button
              class="block w-full px-3 py-1.5 text-xs text-[#e0e0e0] hover:bg-[#545454] text-left"
              @click.stop="HandleFileImport"
            >
              📦 模型
            </button>
            <button
              class="block w-full px-3 py-1.5 text-xs text-[#e0e0e0] hover:bg-[#545454] text-left"
              @click.stop="HandleActorImport"
            >
              👤 单位
            </button>
            <button
              class="block w-full px-3 py-1.5 text-xs text-[#e0e0e0] hover:bg-[#545454] text-left"
              @click.stop="HandleSceneImport"
            >
              🎬 场景
            </button>
            <button
              class="block w-full px-3 py-1.5 text-xs text-[#e0e0e0] hover:bg-[#545454] text-left"
              @click.stop="HandleMultimediaImport"
            >
              🎵 多媒体
            </button>
          </div>
        </div>
        <button
          class="p-1.5 hover:bg-[#545454] rounded text-[#e0e0e0]"
          title="添加灯光"
          @click.stop="ImportLightSource"
        >
          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path
              d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7M9 21v-1h6v1a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1m3-17a5 5 0 0 0-5 5c0 2.05 1.23 3.81 3 4.58V16h4v-2.42c1.77-.77 3-2.53 3-4.58a5 5 0 0 0-5-5z"
            />
          </svg>
        </button>
        <button
          class="p-1.5 hover:bg-[#545454] rounded text-[#e0e0e0]"
          title="添加摄像头"
          @click.stop="ImportCamera"
        >
          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path
              d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"
            />
          </svg>
        </button>
        <div class="w-px h-4 bg-[#1a1a1a] mx-1"></div>
        <button
          class="p-1.5 hover:bg-[#545454] rounded text-[#e0e0e0]"
          title="保存场景"
          @click.stop="SaveScene"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"
            ></path>
          </svg>
        </button>
        <button
          class="p-1.5 hover:bg-[#545454] rounded text-[#e0e0e0]"
          title="截图"
          @click.stop="TakeScreenshot"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
            />
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
        </button>
        <!-- Vision / Native 渲染后端切换（仅 Vision 可用时显示） -->
        <button
          v-if="visionAvailable"
          class="p-1.5 hover:bg-[#545454] rounded flex items-center gap-0.5"
          :class="activeRenderBackend === 'vision' ? 'text-[#34d399]' : 'text-[#e0e0e0]'"
          :title="activeRenderBackend === 'vision' ? '当前: Vision (路径追踪)，点击切换到 Native' : '当前: Native (光栅化)，点击切换到 Vision'"
          @click.stop="ToggleRenderBackend"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M3 12a9 9 0 1018 0 9 9 0 00-18 0zm9-9v18m-9-9h18"
            />
          </svg>
        </button>
        <!-- GBuffer 输出模式切换 -->
        <div class="relative">
          <button
            class="p-1.5 hover:bg-[#545454] rounded flex items-center gap-0.5"
            :class="activeOutputMode === 'final_color' ? 'text-[#e0e0e0]' : 'text-[#c084fc]'"
            title="输出通道"
            @click.stop="ShowGBufferDropdown = !ShowGBufferDropdown"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 6h16M4 10h16M4 14h10M4 18h6"
              />
            </svg>
            <svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>
          <div
            v-if="ShowGBufferDropdown"
            v-click-outside="() => (ShowGBufferDropdown = false)"
            class="absolute z-20 right-0 mt-1 w-36 bg-[#3c3c3c] rounded shadow-lg border border-[#1a1a1a]"
          >
            <div class="px-2 py-1 text-[10px] text-gray-500 border-b border-[#1a1a1a]">
              输出通道
            </div>
            <button
              v-for="buf in outputModes"
              :key="buf.type"
              class="w-full px-3 py-1.5 text-xs hover:bg-[#545454] text-left flex items-center gap-2"
              :class="activeOutputMode === buf.type ? 'text-white bg-[#4a4a4a]' : 'text-[#e0e0e0]'"
              @click.stop="SetOutputMode(buf.type)"
            >
              <span :style="{ color: buf.color }">■</span>
              {{ buf.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- 输出模式快捷切换 & 截图测试 -->
      <div
        class="flex flex-wrap items-center gap-1 px-2 py-1.5 bg-[#2a2a2a] border-b border-[#1a1a1a]"
      >
        <button
          v-for="buf in outputModes"
          :key="'quick-' + buf.type"
          class="px-1.5 py-0.5 text-[10px] rounded border"
          :class="
            activeOutputMode === buf.type
              ? 'border-current font-bold'
              : 'border-[#555] text-[#999] hover:text-[#ccc] hover:border-[#777]'
          "
          :style="activeOutputMode === buf.type ? { color: buf.color, borderColor: buf.color } : {}"
          :title="'切换到 ' + buf.label"
          @click="SetOutputMode(buf.type)"
        >
          {{ buf.label }}
        </button>
        <div class="w-px h-4 bg-[#444] mx-0.5"></div>
        <button
          class="px-1.5 py-0.5 text-[10px] rounded border border-[#555] text-[#4ec9b0] hover:bg-[#3a3a3a]"
          title="快速截图（保存当前输出模式到桌面）"
          @click="QuickScreenshot"
        >
          📷 快速截图
        </button>
        <button
          class="px-1.5 py-0.5 text-[10px] rounded border border-[#555] text-[#dcdcaa] hover:bg-[#3a3a3a]"
          title="依次切换所有通道并逐一截图保存"
          @click="SaveAllBuffers"
        >
          📦 全部保存
        </button>
      </div>

      <!-- 场景树 -->
      <div class="flex-1 overflow-y-auto bg-[#282828]/50">
        <div class="select-none">
          <!-- Cameras 分组 -->
          <div
            class="flex items-center px-2 py-1 bg-[#3c3c3c]/50 border-b border-[#1a1a1a]/30 cursor-pointer"
            @click="camerasExpanded = !camerasExpanded"
          >
            <svg
              class="w-3 h-3 text-[#909090] mr-1 transition-transform"
              :class="{ 'rotate-90': camerasExpanded }"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M10 6l6 6-6 6z" />
            </svg>
            <svg class="w-3.5 h-3.5 text-[#90caf9] mr-1" fill="currentColor" viewBox="0 0 24 24">
              <path
                d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"
              />
            </svg>
            <span class="text-xs text-[#e0e0e0] font-medium">Cameras</span>
            <span class="ml-auto text-xs text-[#666]">{{ sceneCameras.length }}</span>
          </div>
          <div v-show="camerasExpanded" class="pl-2">
            <div v-for="cam in sceneCameras" :key="'cam-' + cam.name">
              <!-- Camera 行 -->
              <div
                class="group flex items-center px-2 py-0.5 hover:bg-[#3c3c3c]/50 cursor-pointer border-l-2 border-transparent hover:border-[#90caf9]"
                :class="{ 'bg-[#264f78]/60': selectedItem === 'cam:' + cam.name }"
                @click="selectedItem = 'cam:' + cam.name"
              >
                <span class="w-5 flex-shrink-0">
                  <svg class="w-4 h-4 text-[#90caf9]" fill="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"
                    />
                  </svg>
                </span>
                <span class="text-xs text-[#e0e0e0] truncate flex-1" :title="cam.name">
                  {{ cam.name }}
                </span>
                <span
                  class="text-[10px] text-[#666] mr-1 hidden group-hover:inline"
                  :title="'fov: ' + (cam.fov != null ? cam.fov.toFixed(1) : '-')"
                >
                  {{ cam.width }}x{{ cam.height }}
                </span>
              </div>
            </div>
            <div v-if="sceneCameras.length === 0" class="px-4 py-2 text-center">
              <span class="text-[10px] text-[#666]">无相机</span>
            </div>
          </div>

          <!-- Scene Collection 分组 -->
          <div
            class="flex items-center px-2 py-1 bg-[#3c3c3c]/50 border-b border-[#1a1a1a]/30 cursor-pointer"
            @click="actorsExpanded = !actorsExpanded"
          >
            <svg
              class="w-3 h-3 text-[#909090] mr-1 transition-transform"
              :class="{ 'rotate-90': actorsExpanded }"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M10 6l6 6-6 6z" />
            </svg>
            <span class="text-xs text-[#e0e0e0] font-medium">Scene Collection</span>
            <span class="ml-auto text-xs text-[#666]">{{ sceneImages.length }}</span>
          </div>

          <!-- 对象列表 -->
          <div v-show="actorsExpanded" class="pl-2">
            <div
              v-for="scene in sceneImages"
              :key="scene.name"
              class="group flex items-center px-2 py-0.5 hover:bg-[#3c3c3c]/50 cursor-pointer border-l-2 border-transparent hover:border-[#84a65b]"
              :class="{ 'bg-[#264f78]/60': selectedItem === scene.name }"
              @click="FocusOnActor(scene)"
              @dblclick="ControlObject(scene)"
            >
              <!-- 图标 -->
              <span class="w-5 flex-shrink-0">
                <template v-if="scene.type === 'light'">
                  <svg class="w-4 h-4 text-[#ffd54f]" fill="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z"
                    />
                  </svg>
                </template>
                <template v-else-if="scene.type === 'camera'">
                  <svg class="w-4 h-4 text-[#90caf9]" fill="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"
                    />
                  </svg>
                </template>
                <template v-else>
                  <svg class="w-4 h-4 text-[#e0e0e0]" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                  </svg>
                </template>
              </span>
              <!-- 名称 -->
              <span class="text-xs text-[#e0e0e0] truncate flex-1" :title="scene.name">
                {{ scene.name }}
              </span>
              <!-- 类型标签 -->
              <span class="text-[10px] text-[#666] mr-2 hidden group-hover:inline">
                {{ getTypeShort(scene.type) }}
              </span>
              <!-- 显隐切换按钮 -->
              <button
                class="w-5 h-5 flex items-center justify-center rounded transition-all mr-0.5"
                :class="
                  scene.visible === false
                    ? 'text-[#555] hover:text-[#999]'
                    : 'text-[#e0e0e0] hover:text-[#ffd54f]'
                "
                :title="scene.visible === false ? '显示' : '隐藏'"
                @click.stop="ToggleVisible(scene)"
              >
                <svg
                  v-if="scene.visible !== false"
                  class="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                  />
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                  />
                </svg>
                <svg
                  v-else
                  class="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"
                  />
                </svg>
              </button>
              <!-- 删除按钮 -->
              <button
                class="w-5 h-5 flex items-center justify-center text-[#666] hover:text-red-400 hover:bg-red-400/20 rounded transition-all"
                title="删除"
                @click.stop="DeleteActor(scene)"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                  />
                </svg>
              </button>
            </div>

            <!-- 空状态 -->
            <div v-if="sceneImages.length === 0" class="px-4 py-8 text-center">
              <span class="text-xs text-[#666]">场景为空，点击 + 添加对象</span>
            </div>
          </div>
        </div>
      </div>
      </div>

      <!-- 底部状态栏 -->
      <div
        class="flex items-center justify-between px-2 py-1 bg-[#3c3c3c]/60 border-t border-[#1a1a1a]/30 text-[10px] text-[#909090]"
      >
        <span>对象: {{ sceneImages.length }}</span>
        <span>{{ currentSceneName }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { useRoute } from 'vue-router';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import { appService, sceneService, projectService, resourceService } from '@/utils/bridge.js';
import { DEFAULT_SCENE_NAME } from '@/utils/constants.js';
import { useErrorHandler } from '@/composables/useErrorHandler.js';
import { setActorContext } from '@/blockly/composables/useActorContext.js';
import { coronaEventBus } from '@/utils/eventBus.js';
import { useDockPanel } from '@/composables/useDockPanel.js';

const { closePanel: closeDockPanel, isDocked } = useDockPanel();

const { error: logError, warn: logWarn } = useErrorHandler('SceneBar');

const getTypeShort = (type) => {
  const lowerType = (type || 'obj').toLowerCase();
  const typeMap = {
    light: 'Light',
    camera: 'Camera',
    obj: 'Mesh',
    fbx: 'Mesh',
    '3ds': 'Mesh',
    dae: 'Mesh',
    gltf: 'Mesh',
    glb: 'Mesh',
    stl: 'Mesh',
    mp4: 'Video',
    avi: 'Video',
    mov: 'Video',
    mp3: 'Audio',
    wav: 'Audio',
    actor: 'Actor',
    model: 'Model',
    mesh: 'Mesh',
    multimedia: 'Media',
  };
  return typeMap[lowerType] || 'Object';
};

const selectedItem = ref(null);
const sceneCameras = ref([]);
const camerasExpanded = ref(true);
const actorsExpanded = ref(true);

const sceneImages = ref([]);
const route = useRoute();
const currentSceneName = ref('');
const px = ref('1.0'),
  py = ref('1.0'),
  pz = ref('1.0');
const recording = ref(false);

// ===========================================================================
//  资源智能搜索(场景栏新增功能)
// ===========================================================================
const searchInput = ref('');
const searchLoading = ref(false);
const searchError = ref('');
const searchResults = ref([]);
const searchLastQuery = ref('');
const searchElapsedMs = ref(0);
const searchSeq = ref(0);        // B-2 竞态保护
const searchDebounce = ref(null);
const imageInputRef = ref(null);
const SEARCH_DEBOUNCE_MS = 250;

const searchActive = computed(() => {
  return searchLoading.value || searchResults.value.length > 0
    || !!searchError.value || !!searchLastQuery.value;
});

const typeIcon = (type) => ({
  model: '📦', actor: '👤', scene: '🎬',
  multimedia: '🎵', terrain: '🏔', script: '📜', other: '📄',
})[type] || '📄';

const typeColorClass = (type) => ({
  model: 'text-[#9cdcfe]',
  actor: 'text-[#ce9178]',
  scene: 'text-[#c586c0]',
  multimedia: 'text-[#dcdcaa]',
  terrain: 'text-[#4ec9b0]',
  script: 'text-[#b5cea8]',
  other: 'text-[#808080]',
})[type] || 'text-[#808080]';

const onSearchInput = () => {
  if (searchDebounce.value) clearTimeout(searchDebounce.value);
  searchDebounce.value = setTimeout(() => {
    doFuzzySearch(searchInput.value);
  }, SEARCH_DEBOUNCE_MS);
};

const onSearchEnter = () => {
  if (searchDebounce.value) clearTimeout(searchDebounce.value);
  doFuzzySearch(searchInput.value);
};

const onSearchClear = () => {
  searchInput.value = '';
  if (searchDebounce.value) clearTimeout(searchDebounce.value);
  searchResults.value = [];
  searchError.value = '';
  searchLastQuery.value = '';
  searchElapsedMs.value = 0;
};

const doFuzzySearch = async (query) => {
  const mySeq = ++searchSeq.value;
  if (!query || !query.trim()) {
    searchResults.value = [];
    searchError.value = '';
    searchLastQuery.value = '';
    return;
  }
  searchLoading.value = true;
  searchError.value = '';
  try {
    const resp = await resourceService.fuzzySearch(query.trim(), 30);
    if (mySeq !== searchSeq.value) return;  // 已被新请求覆盖
    if (resp && resp.success !== false && resp.data) {
      const data = resp.data;
      if (data.status === 'success' || data.status === 'ok') {
        searchResults.value = Array.isArray(data.items) ? data.items : [];
        searchLastQuery.value = query.trim();
        searchElapsedMs.value = data.elapsed_ms || 0;
      } else {
        searchError.value = data.message || '搜索失败';
        searchResults.value = [];
      }
    } else {
      searchError.value = (resp && resp.error) || '搜索请求失败';
      searchResults.value = [];
    }
  } catch (e) {
    if (mySeq !== searchSeq.value) return;
    searchError.value = e?.message || '网络错误';
    searchResults.value = [];
  } finally {
    if (mySeq === searchSeq.value) searchLoading.value = false;
  }
};

const onImageSelected = async (ev) => {
  const file = ev.target.files && ev.target.files[0];
  if (!file) return;
  // B-3 大图片走 base64 时限制大小(> 2MB 警告)
  if (file.size > 5 * 1024 * 1024) {
    searchError.value = `图片过大 (${(file.size / 1024 / 1024).toFixed(1)}MB),请使用 ≤ 2MB 的图片`;
    return;
  }
  const mySeq = ++searchSeq.value;
  searchLoading.value = true;
  searchError.value = '';
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result);
      fr.onerror = () => reject(fr.error);
      fr.readAsDataURL(file);
    });
    const resp = await resourceService.imageSearch(dataUrl, 30, 10);
    if (mySeq !== searchSeq.value) return;
    if (resp && resp.success !== false && resp.data) {
      const data = resp.data;
      if (data.status === 'success') {
        searchResults.value = Array.isArray(data.items) ? data.items : [];
        searchLastQuery.value = `[图] ${file.name}`;
        searchElapsedMs.value = data.elapsed_ms || 0;
      } else {
        searchError.value = data.message || '以图搜索失败';
        searchResults.value = [];
      }
    } else {
      searchError.value = (resp && resp.error) || '以图搜索请求失败';
      searchResults.value = [];
    }
  } catch (e) {
    if (mySeq !== searchSeq.value) return;
    searchError.value = e?.message || '图片读取失败';
    searchResults.value = [];
  } finally {
    if (mySeq === searchSeq.value) searchLoading.value = false;
    if (imageInputRef.value) imageInputRef.value.value = '';
  }
};

const onRebuildIndex = async () => {
  const mySeq = ++searchSeq.value;
  searchLoading.value = true;
  searchError.value = '';
  try {
    const resp = await resourceService.rebuildIndex();
    if (mySeq !== searchSeq.value) return;
    if (resp && resp.success !== false && resp.data && resp.data.status === 'success') {
      const t = resp.data.text || {};
      searchLastQuery.value = `[重建] ${t.count || 0} 项, ${t.elapsed_seconds || 0}s`;
    } else {
      searchError.value = (resp && resp.data && resp.data.message) || '重建索引失败';
    }
  } catch (e) {
    if (mySeq !== searchSeq.value) return;
    searchError.value = e?.message || '重建索引失败';
  } finally {
    if (mySeq === searchSeq.value) searchLoading.value = false;
  }
};

const OnLocateSearchItem = async (item) => {
  // 桥接 ResourceSearch.focus_actor → SceneTools.focus_actor
  // 资源项的 path 形如 Scene/MyScene.actor 或 assets/xxx.fbx
  // 我们尝试从 name 推断 actor,失败则回退到原行为
  try {
    const name = (item.name || '').trim();
    const resp = await resourceService.focusActor(currentSceneName.value, name);
    if (resp && resp.data && resp.data.status === 'success') {
      selectedItem.value = name;
      setActorContext(currentSceneName.value, name);
    } else {
      logWarn('定位资源失败', resp && resp.data && resp.data.message);
    }
  } catch (e) {
    logError('定位资源失败', e);
  }
};

const ControlObject = async (scene) => {
  try {
    await sceneService.openSceneActor(currentSceneName.value, scene.name);
  } catch (e) {
    logError('Failed to open actor', e);
  }
};

const FocusOnActor = async (scene) => {
  selectedItem.value = scene.name;
  // 通知积木编辑器当前选中的物体
  setActorContext(currentSceneName.value, scene.name);
  try {
    const cameraName = getTargetCameraName();
    await sceneService.focusActor(currentSceneName.value, scene.name, cameraName);
    await appService.callDockFunction('', 'syncCameraState', []);
  } catch (e) {
    logWarn('Failed to focus on actor', e);
  }
};

const ToggleVisible = async (scene) => {
  const newVisible = scene.visible === false ? true : false;
  scene.visible = newVisible;
  try {
    await sceneService.actorOperation(currentSceneName.value, scene.name, 'SetVisible', [
      newVisible ? 1 : 0,
    ]);
  } catch (e) {
    scene.visible = !newVisible;
    logError('Failed to toggle visibility', e);
  }
};

const SaveScene = async () => {
  try {
    await projectService.sceneSave(currentSceneName.value);
  } catch (e) {
    logError('Failed to save scene', e);
  }
};

const getTargetCameraName = () => {
  const item = selectedItem.value || '';
  if (item.startsWith('cam:')) {
    return item.slice(4);
  }
  return sceneCameras.value[0]?.name;
};

const TakeScreenshot = async () => {
  try {
    const cameraName = getTargetCameraName();
    const selectResult = await sceneService.selectScreenshotPath(
      currentSceneName.value,
      cameraName
    );
    const selectPayload = selectResult?.data ?? selectResult;

    if (!selectPayload || selectPayload.status === 'canceled' || !selectPayload.path) {
      return;
    }

    const result = await sceneService.saveScreenshot(
      currentSceneName.value,
      selectPayload.path,
      cameraName
    );
    const payload = result?.data ?? result;
    if (result?.success === false || payload?.status === 'error') {
      logError('Screenshot failed', payload?.message || result?.error || 'unknown error');
    }
  } catch (e) {
    logError('Failed to take screenshot', e);
  }
};

const outputModes = [
  { type: 'final_color', label: 'Final Color', color: '#e0e0e0' },
  { type: 'base_color', label: 'Base Color', color: '#60a5fa' },
  { type: 'normal', label: 'Normal', color: '#34d399' },
  { type: 'position', label: 'Position', color: '#fbbf24' },
  { type: 'object_id', label: 'Object ID', color: '#c084fc' },
];
const ShowGBufferDropdown = ref(false);
const activeOutputMode = ref('final_color');

// Vision / Native 渲染后端切换状态
const visionAvailable = ref(false);
const activeRenderBackend = ref('native');

const RefreshRenderBackendState = async () => {
  try {
    const availResult = await sceneService.isVisionAvailable();
    const availPayload = availResult?.data ?? availResult;
    visionAvailable.value = !!availPayload?.available;
    if (!visionAvailable.value) {
      return;
    }
    const modeResult = await sceneService.getRenderBackend();
    const modePayload = modeResult?.data ?? modeResult;
    if (modePayload?.mode) {
      activeRenderBackend.value = modePayload.mode;
    }
  } catch (e) {
    logError('Failed to query render backend state', e);
  }
};

const ToggleRenderBackend = async () => {
  const next = activeRenderBackend.value === 'vision' ? 'native' : 'vision';
  try {
    const result = await sceneService.setRenderBackend(next);
    const payload = result?.data ?? result;
    if (result?.success === false || payload?.status === 'error') {
      logError('Switch render backend failed', payload?.message || result?.error || 'unknown error');
    } else {
      activeRenderBackend.value = next;
    }
  } catch (e) {
    logError('Failed to switch render backend', e);
  }
};

const SetOutputMode = async (mode) => {
  ShowGBufferDropdown.value = false;
  try {
    const cameraName = getTargetCameraName();
    const result = await sceneService.setOutputMode(currentSceneName.value, cameraName, mode);
    const payload = result?.data ?? result;
    if (result?.success === false || payload?.status === 'error') {
      logError(`Set output mode failed`, payload?.message || result?.error || 'unknown error');
    } else {
      activeOutputMode.value = mode;
    }
  } catch (e) {
    logError('Failed to set output mode', e);
  }
};

const QuickScreenshot = async () => {
  try {
    const cameraName = getTargetCameraName();
    const selectResult = await sceneService.selectScreenshotPath(
      currentSceneName.value,
      cameraName
    );
    const selectPayload = selectResult?.data ?? selectResult;
    if (!selectPayload || selectPayload.status === 'canceled' || !selectPayload.path) {
      return;
    }
    // Insert current mode name before file extension
    const path = selectPayload.path;
    const dotIdx = path.lastIndexOf('.');
    const taggedPath =
      dotIdx > 0
        ? path.slice(0, dotIdx) + '_' + activeOutputMode.value + path.slice(dotIdx)
        : path + '_' + activeOutputMode.value + '.png';

    const result = await sceneService.saveScreenshot(
      currentSceneName.value,
      taggedPath,
      cameraName
    );
    const payload = result?.data ?? result;
    if (result?.success === false || payload?.status === 'error') {
      logError('Quick screenshot failed', payload?.message || result?.error || 'unknown error');
    }
  } catch (e) {
    logError('Failed to take quick screenshot', e);
  }
};

const SaveAllBuffers = async () => {
  try {
    const cameraName = getTargetCameraName();
    const selectResult = await sceneService.selectScreenshotPath(
      currentSceneName.value,
      cameraName
    );
    const selectPayload = selectResult?.data ?? selectResult;
    if (!selectPayload || selectPayload.status === 'canceled' || !selectPayload.path) {
      return;
    }
    const basePath = selectPayload.path;
    const dotIdx = basePath.lastIndexOf('.');
    const stem = dotIdx > 0 ? basePath.slice(0, dotIdx) : basePath;
    const ext = dotIdx > 0 ? basePath.slice(dotIdx) : '.png';

    const previousMode = activeOutputMode.value;

    for (const buf of outputModes) {
      // Switch mode
      await sceneService.setOutputMode(currentSceneName.value, cameraName, buf.type);
      activeOutputMode.value = buf.type;

      // Wait one frame for GPU to render with new mode
      await new Promise((resolve) => setTimeout(resolve, 200));

      // Save screenshot
      const filePath = stem + '_' + buf.type + ext;
      const result = await sceneService.saveScreenshot(
        currentSceneName.value,
        filePath,
        cameraName
      );
      const payload = result?.data ?? result;
      if (result?.success === false || payload?.status === 'error') {
        logError(`Save ${buf.label} failed`, payload?.message || result?.error || 'unknown error');
      }
    }

    // Restore previous mode
    await sceneService.setOutputMode(currentSceneName.value, cameraName, previousMode);
    activeOutputMode.value = previousMode;
  } catch (e) {
    logError('Failed to save all buffers', e);
  }
};

const ShowModelDropdown = ref(false);
const ToggleModelDropdown = () => {
  ShowModelDropdown.value = !ShowModelDropdown.value;
};
const CloseModelDropdown = () => {
  ShowModelDropdown.value = false;
};

const generateUniqueName = (baseName) => {
  let name = baseName;
  let counter = 1;
  while (sceneImages.value.find((item) => item.name === name)) {
    name = `${baseName}_${counter}`;
    counter++;
  }
  return name;
};

const LIGHT_MODEL_PATH = 'assets/editor/Ball.obj';
const CAMERA_MODEL_PATH = 'assets/editor/Ball.obj';

const ImportLightSource = async () => {
  ShowModelDropdown.value = false;
  const lightName = generateUniqueName('Light');
  await addActorToList({
    name: lightName,
    path: LIGHT_MODEL_PATH,
    type: 'light',
  });
};

const ImportCamera = async () => {
  ShowModelDropdown.value = false;
  const cameraName = generateUniqueName('Camera');
  await addActorToList({
    name: cameraName,
    path: CAMERA_MODEL_PATH,
    type: 'camera',
  });
};

const addActorToList = async (actor) => {
  if (!actor || !actor.name) return;
  sceneImages.value.push({
    name: actor.name,
    path: actor.path,
    type: actor.type || 'obj',
    visible: actor.visible !== false,
  });
};

const HandleFileImport = async () => {
  // 测试 window.cefQuery 是否存在
  if (typeof window.cefQuery === 'undefined') {
    alert('错误：window.cefQuery 未定义！CEF bridge 未初始化。');
    return;
  }

  ShowModelDropdown.value = false;
  if (!currentSceneName.value) {
    logWarn('File import aborted: no active scene');
    return;
  }
  try {
    await appService.callDockFunction('', 'showLoading', ['加载中', '请稍候...', 0]);
  } catch (e) {
    // showLoading 失败不阻塞主流程
  }
  try {
    const result = await projectService.importResourceFileByDialog(currentSceneName.value, 'model');
    // 兼容两种返回形态:
    //   1) 包装型 { success, data: { status, actor, ... } }
    //   2) 直返型 { status, actor, ... }
    const payload = result?.data ?? result;
    const status = payload?.status;
    if (result?.success === false || status === 'error') {
      logError('File import failed', payload?.message || result?.error || 'unknown error');
      return;
    }
    if (status === 'canceled') {
      // 用户主动取消,无需弹错
      return;
    }
    const actor = payload?.actor;
    if (actor && actor.name) {
      await addActorToList(actor);
      try {
        await appService.callDockFunction('', 'updateLoading', ['导入完成', 100]);
      } catch (e) {
        // 忽略加载条更新失败
      }
    } else {
      logWarn('File import returned without actor payload', payload);
    }
  } catch (e) {
    logError('File import failed', e);
  } finally {
    try {
      await appService.callDockFunction('', 'hideLoading', []);
    } catch (e) {
      // 忽略关闭加载条失败
    }
  }
};

const HandleActorImport = async () => {
  ShowModelDropdown.value = false;
  await appService.callDockFunction('', 'showLoading', ['加载中', '请稍候...', 0]);
  try {
    const result = await projectService.importResourceFileByDialog(currentSceneName.value, 'actor');
    if (result.success && result.data.actor) {
      await addActorToList(result.data.actor);
      await appService.callDockFunction('', 'updateLoading', ['导入完成', 100]);
    }
  } catch (e) {
    logError('Actor import failed', e);
  }
  await appService.callDockFunction('', 'hideLoading', []);
};

const HandleMultimediaImport = async () => {
  ShowModelDropdown.value = false;
  await appService.callDockFunction('', 'showLoading', ['加载中', '请稍候...', 0]);
  try {
    const result = await projectService.importResourceFileByDialog(
      currentSceneName.value,
      'multimedia'
    );
    if (result.success && result.data.actor) {
      await addActorToList(result.data.actor);
      await appService.callDockFunction('', 'updateLoading', ['导入完成', 100]);
    }
  } catch (e) {
    logError('Multimedia import failed', e);
  }
  await appService.callDockFunction('', 'hideLoading', []);
};

const HandleSceneImport = async () => {
  ShowModelDropdown.value = false;
  await appService.callDockFunction('', 'showLoading', ['加载中', '请稍候...', 0]);
  try {
    const result = await projectService.importResourceFileByDialog(currentSceneName.value, 'scene');
    if (result.success === true) {
      await appService.callDockFunction('', 'updateLoading', ['导入中', 40]);
      if (Array.isArray(result.data.actors)) {
        sceneImages.value = sceneImages.value.concat(
          result.data.actors.map((actor) => ({
            name: actor.name || actor.path.split('/').pop().split('.')[0],
            path: actor.path,
            type: actor.type || 'obj',
          }))
        );
      }

      await appService.callDockFunction('', 'updateLoading', ['导入完成', 100]);
    }
  } catch (e) {
    logError('Scene import failed', e);
  }
  await appService.callDockFunction('', 'hideLoading', []);
};

const DeleteActor = async (scene) => {
  sceneImages.value = sceneImages.value.filter((item) => item.name !== scene.name);

  try {
    //await appService.removeDockWidget(`Object_${scene.name}`);
  } catch {
    // 忽略
  }

  try {
    await sceneService.removeActor(currentSceneName.value, scene.name);
  } catch {
    // 忽略
  }
};

const CloseFloat = async () => {
  if (closeDockPanel) { closeDockPanel(); return; }
  await appService.removeDockWidget('SceneTools');
};

const setupFragmentListener = () => {
  window.onFragmentChanged = (fragment) => {
    const queryString = fragment.split('?')[1];
    if (!queryString) return;
    console.log(queryString);
    const params = new URLSearchParams(queryString);
    const sceneName = params.get('sceneName');

    if (sceneName) {
      // 无论 sceneName 是否变化，都要刷新 actor 列表
      // 场景切换后后端数据已更新，必须重新拉取
      currentSceneName.value = sceneName;
      OnInitObjTree();
    }
  };

  window.onSceneTreeChanged = (sceneName) => {
    if (!sceneName || sceneName === currentSceneName.value) {
      OnInitObjTree();
    }
  };
};

const OnInitObjTree = async () => {
  try {
    const result = await sceneService.listSceneTree(currentSceneName.value);
    sceneImages.value = [];
    sceneCameras.value = [];

    if (result.success && result.data) {
      const data = result.data;

      if (Array.isArray(data.actors)) {
        data.actors.forEach((item) => {
          sceneImages.value.push({
            name: item.name,
            path: item.path,
            type: item.type || 'obj',
            visible: item.visible !== false,
          });
        });
      }

      if (Array.isArray(data.cameras)) {
        sceneCameras.value = data.cameras.map((cam) => ({
          name: cam.name || 'Camera',
          width: cam.width || 0,
          height: cam.height || 0,
          fov: cam.fov ?? null,
        }));
      }
    }
  } catch (e) {
    logError('Failed to load scene tree', e);
  }
};

onMounted(async () => {
  const result = await projectService.OnInit();
  const queryString = window.location.hash?.split('?')[1] || window.location.search?.slice(1);
  const urlSceneName = queryString ? new URLSearchParams(queryString).get('sceneName') : null;

  // 从 OnInit 返回值中取活跃场景：scenes 数组 + active_index
  const initData = result?.data ?? result;
  const activeScene = initData?.scenes?.[initData?.active_index ?? 0];
  currentSceneName.value = urlSceneName || activeScene?.path || DEFAULT_SCENE_NAME;

  setupFragmentListener();
  await OnInitObjTree();
  await RefreshRenderBackendState();

  // 监听 Python 推送的 actor-change：场景切换/物体变化时重新加载场景树
  coronaEventBus.on('actor-change', onActorChangeEvent);
  coronaEventBus.on('scene-tree-changed', onSceneTreeChangedEvent);
});

// 场景切换或 actor 变化时刷新当前场景树
const onActorChangeEvent = (type, sceneId /*, actorId, oldPath */) => {
  if (type === 'scene' && sceneId) {
    currentSceneName.value = sceneId;
  }
  OnInitObjTree();
};

const onSceneTreeChangedEvent = (sceneName) => {
  if (!sceneName || sceneName === currentSceneName.value) {
    OnInitObjTree();
  }
};

onUnmounted(() => {
  coronaEventBus.off('actor-change', onActorChangeEvent);
  coronaEventBus.off('scene-tree-changed', onSceneTreeChangedEvent);
});
</script>
