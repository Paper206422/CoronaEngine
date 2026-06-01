<template>
  <div class="rounded-lg overflow-hidden relative bg-[#282828]/70 min-h-screen flex flex-col">
    <DockTitleBar
      title="详情"
      extraClass="bg-[#84A65B] rounded-t-md text-sm"
      routePath="/Object"
      @close="CloseFloat"
    />

    <!-- 主标签页 - 场景、单位、模型 -->
    <div class="bg-[#3c3c3c]/60 border-b border-[#1a1a1a]/30">
      <div class="flex px-2">
        <!-- 场景标签 -->
        <div
          class="flex-1 px-4 py-2 cursor-pointer transition-all duration-200 ease-in-out text-center text-xs"
          :class="{
            'bg-[#264f78]/60 text-white border-b-2 border-[#84a65b]': mainActiveTab === 'scene',
            'hover:bg-[#545454] text-[#e0e0e0]': mainActiveTab !== 'scene',
          }"
          @click="switchMainTab('scene')"
        >
          <span class="select-none font-medium">场景</span>
        </div>

        <!-- 单位标签 -->
        <div
          class="flex-1 px-4 py-2 cursor-pointer transition-all duration-200 ease-in-out text-center text-xs"
          :class="{
            'bg-[#264f78]/60 text-white border-b-2 border-[#84a65b]':
              mainActiveTab === 'actor' && currentActorFile,
            'bg-[#3c3c3c]/30 text-gray-500 border-b-2 border-[#84a65b]/30':
              mainActiveTab === 'actor' && !currentActorFile,
            'hover:bg-[#545454] text-[#e0e0e0]': mainActiveTab !== 'actor',
          }"
          @click="switchMainTab('actor')"
        >
          <span class="select-none font-medium">单位</span>
        </div>

        <!-- 模型标签 -->
        <div
          class="flex-1 px-4 py-2 cursor-pointer transition-all duration-200 ease-in-out text-center text-xs"
          :class="{
            'bg-[#264f78]/60 text-white border-b-2 border-[#84a65b]':
              mainActiveTab === 'model' && currentModelFile,
            'bg-[#3c3c3c]/30 text-gray-500 border-b-2 border-[#84a65b]/30':
              mainActiveTab === 'model' && !currentModelFile,
            'hover:bg-[#545454] text-[#e0e0e0]': mainActiveTab !== 'model',
          }"
          @click="switchMainTab('model')"
        >
          <span class="select-none font-medium">模型</span>
        </div>
      </div>
    </div>

    <!-- 主内容区域 -->
    <div class="flex flex-col flex-1 bg-[#282828]/70">
      <!-- 当前文件信息 -->
      <div class="flex items-center gap-2 px-2 py-1.5 bg-[#3c3c3c]/60 border-b border-[#1a1a1a]/30">
        <div class="text-[10px] text-[#909090] truncate flex-1">
          <span class="text-[#84a65b] font-bold">{{ currentFileInfo }}</span>
        </div>
      </div>

      <!-- 未打开文件提示 - 只对单位和模型标签显示 -->
      <div
        v-if="
          (mainActiveTab === 'actor' && !currentActorFile) ||
          (mainActiveTab === 'model' && !currentModelFile)
        "
        class="flex-1 flex items-center justify-center text-[#909090] text-xs"
      >
        <span>未打开文件</span>
      </div>

      <!-- 内容区域 - 仅在文件已打开时显示 -->
      <template v-else>
        <!-- 次级标签页（根据主标签动态显示） -->
        <div
          v-if="mainActiveTab === 'scene'"
          class="flex bg-[#3c3c3c]/30 border-b border-[#1a1a1a]/30"
        >
          <button
            v-for="tab in sceneTabs"
            :key="tab.id"
            :class="[
              ActiveSubTab === tab.id
                ? 'bg-[#264f78]/60 text-white'
                : 'text-[#909090] hover:bg-[#545454] hover:text-[#e0e0e0]',
            ]"
            class="flex-1 px-2 py-1 text-xs transition-colors duration-200"
            @click="ActiveSubTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </div>

        <div
          v-else-if="mainActiveTab === 'actor'"
          class="flex bg-[#3c3c3c]/30 border-b border-[#1a1a1a]/30"
        >
          <button
            v-for="tab in actorTabs"
            :key="tab.id"
            :class="[
              ActiveSubTab === tab.id
                ? 'bg-[#264f78]/60 text-white'
                : 'text-[#909090] hover:bg-[#545454] hover:text-[#e0e0e0]',
            ]"
            class="flex-1 px-2 py-1 text-xs transition-colors duration-200"
            @click="ActiveSubTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </div>

        <div
          v-else-if="mainActiveTab === 'model'"
          class="flex bg-[#3c3c3c]/30 border-b border-[#1a1a1a]/30"
        >
          <button
            v-for="tab in modelTabs"
            :key="tab.id"
            :class="[
              ActiveSubTab === tab.id
                ? 'bg-[#264f78]/60 text-white'
                : 'text-[#909090] hover:bg-[#545454] hover:text-[#e0e0e0]',
            ]"
            class="flex-1 px-2 py-1 text-xs transition-colors duration-200"
            @click="ActiveSubTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- ========== 内容区域 ========== -->
        <div class="flex-1 overflow-auto bg-[#282828]/50 p-2">
          <!-- ===== 场景内容 ===== -->
          <template v-if="mainActiveTab === 'scene'">
            <!-- 场景 - 基础信息 -->
            <div v-show="ActiveSubTab === 'Basic'" class="space-y-2 text-xs">
              <!-- 光照设置 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-yellow-600">
                <div class="flex items-center justify-between mb-2">
                  <label class="text-[#e0e0e0] font-medium text-xs">光照</label>
                  <div class="flex items-center space-x-2">
                    <label class="text-[#909090] text-[10px]">启用</label>
                    <input
                      v-model="sceneData.light.enabled"
                      type="checkbox"
                      class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b] w-3 h-3"
                      @change="updateLightDirection"
                    />
                  </div>
                </div>

                <div v-if="sceneData.light.enabled" class="space-y-1">
                  <!-- 方向标签 -->
                  <div class="text-[#909090] text-[10px] mb-1">方向</div>
                  <!-- 方向输入框 -->
                  <div class="grid grid-cols-3 gap-1">
                    <div class="flex items-center gap-1">
                      <label class="text-red-400 text-[10px] w-3">X</label>
                      <NumberInputWithSlider
                        v-model="sceneData.light.direction.x"
                        :step="0.1"
                        :min="-10"
                        :max="10"
                        @change="updateLightDirection"
                      />
                    </div>
                    <div class="flex items-center gap-1">
                      <label class="text-blue-400 text-[10px] w-3">Y</label>
                      <NumberInputWithSlider
                        v-model="sceneData.light.direction.y"
                        :step="0.1"
                        :min="-10"
                        :max="10"
                        @change="updateLightDirection"
                      />
                    </div>
                    <div class="flex items-center gap-1">
                      <label class="text-green-400 text-[10px] w-3">Z</label>
                      <NumberInputWithSlider
                        v-model="sceneData.light.direction.z"
                        :step="0.1"
                        :min="-10"
                        :max="10"
                        @change="updateLightDirection"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 网格设置 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-cyan-600">
                <div class="flex items-center justify-between">
                  <label class="text-[#e0e0e0] font-medium text-xs">网格</label>
                  <div class="flex items-center space-x-2">
                    <label class="text-[#909090] text-[10px]">显示</label>
                    <input
                      v-model="sceneData.grid.enabled"
                      type="checkbox"
                      class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b] w-3 h-3"
                      @change="updateFloorGrid"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- 场景 - 地形 -->
            <div v-show="ActiveSubTab === 'Terrain'" class="space-y-2 text-xs">
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-green-600">
                <div class="flex items-center mb-2">
                  <label class="text-[#e0e0e0] font-medium w-16">地形</label>
                  <select
                    v-model="sceneData.terrain.type"
                    class="flex-1 p-1 bg-[#1a1a1a] text-[#e0e0e0] rounded border border-[#3c3c3c] focus:border-[#84a65b] focus:outline-none text-[10px]"
                  >
                    <option value="none">无</option>
                    <option value="plane">平面</option>
                    <option value="custom">自定义</option>
                  </select>
                </div>

                <div v-if="sceneData.terrain.type === 'custom'" class="mt-2 flex space-x-1">
                  <input
                    v-model="sceneData.terrain.path"
                    type="text"
                    readonly
                    class="flex-1 p-1 bg-[#1a1a1a] text-[#e0e0e0] rounded border border-[#3c3c3c] text-[10px]"
                    placeholder="选择地形文件"
                  />
                  <button
                    class="px-2 py-1 bg-[#545454] text-[#e0e0e0] rounded hover:bg-[#686868] whitespace-nowrap text-[10px]"
                    @click="selectTerrainFile"
                  >
                    浏览
                  </button>
                </div>

                <div v-if="sceneData.terrain.type === 'plane'" class="mt-2">
                  <div class="flex items-center space-x-2">
                    <label class="text-[#909090] w-16">尺寸</label>
                    <NumberInputWithSlider
                      v-model="sceneData.terrain.size"
                      :step="0.1"
                      :min="0.1"
                      :max="100"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- 场景 - 脚本 -->
            <div v-show="ActiveSubTab === 'Script'" class="space-y-2 text-xs">
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-blue-600">
                <div class="flex items-center space-x-2">
                  <label class="text-[#e0e0e0] font-medium w-16">脚本</label>
                  <div class="flex-1 flex space-x-1">
                    <input
                      v-model="sceneData.script.path"
                      type="text"
                      readonly
                      class="flex-1 p-1 bg-[#1a1a1a] text-[#e0e0e0] rounded border border-[#3c3c3c] text-[10px]"
                      placeholder="选择脚本文件"
                    />
                    <button
                      class="px-2 py-1 bg-[#545454] text-[#e0e0e0] rounded hover:bg-[#686868] whitespace-nowrap text-[10px]"
                      @click="selectSceneScript"
                    >
                      浏览
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- ===== 单位内容 ===== -->
          <template v-else-if="mainActiveTab === 'actor'">
            <!-- 单位 - 基础信息 -->
            <div v-show="ActiveSubTab === 'Basic'" class="space-y-2 text-xs">
              <div class="bg-[#3c3c3c]/50 p-2 rounded">
                <div class="flex items-center space-x-2">
                  <label class="text-[#e0e0e0] font-medium w-16">场景</label>
                  <div class="flex-1 text-[#909090] text-[10px] bg-[#1a1a1a] p-1 rounded">
                    {{ actorData.parentScene || '未指定' }}
                  </div>
                </div>
              </div>

              <div class="bg-[#3c3c3c]/50 p-2 rounded">
                <div class="flex items-center space-x-2">
                  <label class="text-[#e0e0e0] font-medium w-16">文件</label>
                  <div class="flex-1 text-[#909090] truncate text-[10px]" :title="currentActorFile">
                    {{ currentActorFile.split('/').pop() }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 单位 - 模型 -->
            <div v-show="ActiveSubTab === 'Model'" class="space-y-2 text-xs">
              <!-- 模型路径 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-green-600">
                <div class="flex items-center space-x-2 mb-2">
                  <label class="text-[#e0e0e0] font-medium w-16">模型</label>
                  <div class="flex-1 flex space-x-1">
                    <input
                      v-model="actorData.model.path"
                      type="text"
                      readonly
                      class="flex-1 p-1 bg-[#1a1a1a] text-[#e0e0e0] rounded border border-[#3c3c3c] text-[10px]"
                      placeholder="选择模型文件"
                    />
                    <button
                      class="px-2 py-1 bg-[#545454] text-[#e0e0e0] rounded hover:bg-[#686868] whitespace-nowrap text-[10px]"
                      @click="selectModelFile"
                    >
                      浏览
                    </button>
                  </div>
                </div>

                <div
                  class="h-16 bg-[#1a1a1a] rounded flex items-center justify-center text-[#909090] text-[10px]"
                >
                  <span v-if="!actorData.model.path">未选择模型</span>
                  <span v-else class="truncate px-2">{{ actorData.model.path }}</span>
                </div>
              </div>

              <!-- 变换 - 只有选择了模型才显示 -->
              <template v-if="actorData.model.path">
                <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-blue-600">
                  <!-- 相机锁定开关 -->
                  <div class="flex items-center justify-between mb-2 pb-2 border-b border-[#1a1a1a]/50">
                    <div class="flex items-center gap-1">
                      <span class="text-pink-400 text-[10px]">&#9679;</span>
                      <label class="text-[#e0e0e0] font-medium text-[10px]">相机锁定</label>
                    </div>
                    <div class="flex items-center space-x-2">
                      <label class="text-[#909090] text-[10px]">启用</label>
                      <input
                        v-model="actorData.camera_lock.lock_to_camera"
                        type="checkbox"
                        class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-pink-500 w-3 h-3"
                        @change="updateCameraLock"
                      />
                    </div>
                  </div>

                  <!-- 相机锁定偏移（启用后显示） -->
                  <div v-if="actorData.camera_lock.lock_to_camera" class="mb-2 pb-2 border-b border-[#1a1a1a]/50">
                    <div class="text-pink-400 text-[10px] mb-1">锁定偏移</div>
                    <div class="grid grid-cols-3 gap-1 mb-1">
                      <div class="flex items-center gap-1">
                        <label class="text-red-400 text-[10px] w-3">X</label>
                        <NumberInputWithSlider
                          v-model="actorData.camera_lock.position_offset.x"
                          :step="0.1" :min="-20" :max="20"
                          @change="updateCameraLockOffset"
                        />
                      </div>
                      <div class="flex items-center gap-1">
                        <label class="text-blue-400 text-[10px] w-3">Y</label>
                        <NumberInputWithSlider
                          v-model="actorData.camera_lock.position_offset.y"
                          :step="0.1" :min="-20" :max="20"
                          @change="updateCameraLockOffset"
                        />
                      </div>
                      <div class="flex items-center gap-1">
                        <label class="text-green-400 text-[10px] w-3">Z</label>
                        <NumberInputWithSlider
                          v-model="actorData.camera_lock.position_offset.z"
                          :step="0.1" :min="-20" :max="20"
                          @change="updateCameraLockOffset"
                        />
                      </div>
                    </div>
                  </div>

                  <label class="text-[#e0e0e0] font-medium block mb-1 text-[10px]">变换 [v3]</label>

                  <!-- 位置 -->
                  <div class="mb-1">
                    <div class="text-[#909090] text-[10px] mb-0.5">位置</div>
                    <div class="grid grid-cols-3 gap-1">
                      <div class="flex items-center gap-1">
                        <label class="text-red-400 text-[10px] w-3">X</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.position.x"
                          :step="0.1"
                          :min="-100"
                          :max="100"
                          @update:model-value="(value) => updateActorTransformFast('Move', 'x', value)"
                          @change="() => updateActorTransform('Move')"
                        />
                      </div>
                      <div class="flex items-center gap-1">
                        <label class="text-blue-400 text-[10px] w-3">Y</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.position.y"
                          :step="0.1"
                          :min="-100"
                          :max="100"
                          @update:model-value="(value) => updateActorTransformFast('Move', 'y', value)"
                          @change="() => updateActorTransform('Move')"
                        />
                      </div>
                      <div class="flex items-center gap-1">
                        <label class="text-green-400 text-[10px] w-3">Z</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.position.z"
                          :step="0.1"
                          :min="-100"
                          :max="100"
                          @update:model-value="(value) => updateActorTransformFast('Move', 'z', value)"
                          @change="() => updateActorTransform('Move')"
                        />
                      </div>
                    </div>
                  </div>

                  <!-- 旋转 -->
                  <div class="mb-1">
                    <div class="text-[#909090] text-[10px] mb-0.5">旋转</div>
                    <div class="grid grid-cols-3 gap-1">
                      <div class="flex items-center gap-1">
                        <label class="text-red-400 text-[10px] w-3">X</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.rotation.x"
                          :step="0.1"
                          :min="-360"
                          :max="360"
                          @update:model-value="(value) => updateActorTransformFast('Rotate', 'x', value)"
                          @change="() => updateActorTransform('Rotate')"
                        />
                      </div>

                      <div class="flex items-center gap-1">
                        <label class="text-blue-400 text-[10px] w-3">Y</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.rotation.y"
                          :step="0.1"
                          :min="-360"
                          :max="360"
                          @update:model-value="(value) => updateActorTransformFast('Rotate', 'y', value)"
                          @change="() => updateActorTransform('Rotate')"
                        />
                      </div>

                      <div class="flex items-center gap-1">
                        <label class="text-green-400 text-[10px] w-3">Z</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.rotation.z"
                          :step="0.1"
                          :min="-360"
                          :max="360"
                          @update:model-value="(value) => updateActorTransformFast('Rotate', 'z', value)"
                          @change="() => updateActorTransform('Rotate')"
                        />
                      </div>
                    </div>
                  </div>

                  <!-- 缩放 -->
                  <div>
                    <div class="text-[#909090] text-[10px] mb-0.5">缩放</div>
                    <div class="grid grid-cols-3 gap-1">
                      <div class="flex items-center gap-1">
                        <label class="text-red-400 text-[10px] w-3">X</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.scale.x"
                          :step="0.1"
                          :min="0.01"
                          :max="10"
                          @update:model-value="(value) => updateActorTransformFast('Scale', 'x', value)"
                          @change="() => updateActorTransform('Scale')"
                        />
                      </div>

                      <div class="flex items-center gap-1">
                        <label class="text-blue-400 text-[10px] w-3">Y</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.scale.y"
                          :step="0.1"
                          :min="0.01"
                          :max="10"
                          @update:model-value="(value) => updateActorTransformFast('Scale', 'y', value)"
                          @change="() => updateActorTransform('Scale')"
                        />
                      </div>

                      <div class="flex items-center gap-1">
                        <label class="text-green-400 text-[10px] w-3">Z</label>
                        <NumberInputWithSlider
                          v-model="actorData.transform.scale.z"
                          :step="0.1"
                          :min="0.01"
                          :max="10"
                          @update:model-value="(value) => updateActorTransformFast('Scale', 'z', value)"
                          @change="() => updateActorTransform('Scale')"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 碰撞选项 -->
                <div
                  v-if="actorData.hasGeometry"
                  class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-orange-600"
                >
                  <div class="flex items-center justify-between">
                    <label class="text-[#e0e0e0] font-medium">碰撞</label>
                    <div class="flex items-center space-x-4">
                      <label class="text-[#909090] text-[10px] flex items-center space-x-1">
                        <input
                          v-model="actorData.collision.type"
                          type="radio"
                          value="none"
                          class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b]"
                        />
                        <span>无</span>
                      </label>
                      <label class="text-[#909090] text-[10px] flex items-center space-x-1">
                        <input
                          v-model="actorData.collision.type"
                          type="radio"
                          value="box"
                          class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b]"
                        />
                        <span>包围盒</span>
                      </label>
                      <label class="text-[#909090] text-[10px] flex items-center space-x-1">
                        <input
                          v-model="actorData.collision.type"
                          type="radio"
                          value="mesh"
                          class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b]"
                        />
                        <span>网格</span>
                      </label>
                    </div>
                  </div>
                </div>

                <!-- 物理属性 -->
                <div
                  v-if="actorData.hasMechanics"
                  class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-purple-600"
                >
                  <label class="text-[#e0e0e0] font-medium block mb-1 text-[10px]">物理</label>
                  <!-- 质量 -->
                  <div class="mb-1">
                    <div class="text-[#909090] text-[10px] mb-0.5">质量</div>
                    <div class="flex items-center bg-[#1a1a1a] rounded px-1 py-0.5">
                      <NumberInputWithSlider
                        v-model="actorData.mechanics.mass"
                        :step="0.1"
                        :min="0.01"
                        :max="100"
                        @change="() => updateActorMechanics('SetMass')"
                      />
                    </div>
                  </div>
                  <!-- 弹性系数 -->
                  <div class="mb-1">
                    <div class="text-[#909090] text-[10px] mb-0.5">弹性系数</div>
                    <div class="flex items-center bg-[#1a1a1a] rounded px-1 py-0.5">
                      <NumberInputWithSlider
                        v-model="actorData.mechanics.restitution"
                        :step="0.05"
                        :min="0"
                        :max="1"
                        @change="() => updateActorMechanics('SetRestitution')"
                      />
                    </div>
                  </div>
                  <!-- 阻尼 -->
                  <div>
                    <div class="text-[#909090] text-[10px] mb-0.5">阻尼</div>
                    <div class="flex items-center bg-[#1a1a1a] rounded px-1 py-0.5">
                      <NumberInputWithSlider
                        v-model="actorData.mechanics.damping"
                        :step="0.01"
                        :min="0"
                        :max="1"
                        @change="() => updateActorMechanics('SetDamping')"
                      />
                    </div>
                  </div>
                </div>
              </template>

              <!-- 未选择模型时的提示 -->
              <div
                v-else
                class="bg-[#3c3c3c]/50 p-4 rounded text-center text-[#909090] text-[10px]"
              >
                请先选择模型文件
              </div>
            </div>

            <!-- 单位 - 积木 -->
            <div v-show="ActiveSubTab === 'Blockly'" style="height: 400px;">
              <BlocklyWorkspace
                v-if="actorData.name"
                :actorName="actorData.name"
                :sceneName="actorData.parentScene || sceneData.name"
                embedded
              />
              <div v-else class="flex items-center justify-center h-full text-[#909090] text-xs">
                请先选中一个物体
              </div>
            </div>

            <!-- 单位 - 脚本 -->
            <div v-show="ActiveSubTab === 'Script'" class="space-y-2 text-xs">
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-blue-600">
                <div class="flex items-center space-x-2">
                  <label class="text-[#e0e0e0] font-medium w-16">脚本</label>
                  <div class="flex-1 flex space-x-1">
                    <input
                      v-model="actorData.script.path"
                      type="text"
                      readonly
                      class="flex-1 p-1 bg-[#1a1a1a] text-[#e0e0e0] rounded border border-[#3c3c3c] text-[10px]"
                      placeholder="选择脚本文件"
                    />
                    <button
                      class="px-2 py-1 bg-[#545454] text-[#e0e0e0] rounded hover:bg-[#686868] whitespace-nowrap text-[10px]"
                      @click="selectActorScript"
                    >
                      浏览
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- ===== 模型内容 ===== -->
          <template v-else-if="mainActiveTab === 'model'">
            <!-- 模型 - 基础信息 -->
            <div v-show="ActiveSubTab === 'Basic'" class="space-y-2 text-xs">
              <div class="bg-[#3c3c3c]/50 p-2 rounded">
                <div class="flex items-center space-x-2">
                  <label class="text-[#e0e0e0] font-medium w-16">场景</label>
                  <div class="flex-1 text-[#909090] text-[10px] bg-[#1a1a1a] p-1 rounded">
                    {{ modelData.targetScene || '未指定' }}
                  </div>
                </div>
              </div>

              <div class="bg-[#3c3c3c]/50 p-2 rounded">
                <div class="flex items-center space-x-2">
                  <label class="text-[#e0e0e0] font-medium w-16">文件</label>
                  <div class="flex-1 text-[#909090] truncate text-[10px]" :title="currentModelFile">
                    {{ currentModelFile.split('/').pop() }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 模型 - 模型设置 -->
            <div v-show="ActiveSubTab === 'Model'" class="space-y-2 text-xs">
              <!-- 模型路径 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-green-600">
                <label class="text-[#e0e0e0] font-medium block mb-1">模型文件</label>
                <div
                  class="text-[#909090] text-[10px] bg-[#1a1a1a] p-1 rounded truncate"
                  :title="currentModelFile"
                >
                  {{ modelData.file }}
                </div>
              </div>

              <!-- 变换 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-blue-600">
                <label class="text-[#e0e0e0] font-medium block mb-1 text-[10px]">默认变换</label>

                <!-- 位置 -->
                <div class="mb-1">
                  <div class="text-[#909090] text-[10px] mb-0.5">位置</div>
                  <div class="grid grid-cols-3 gap-1">
                    <div class="flex items-center gap-1">
                      <label class="text-red-400 text-[10px] w-3">X</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.position.x"
                        :step="0.1"
                        :min="-100"
                        :max="100"
                        @update:model-value="(value) => updateModelTransformFast('Move', 'x', value)"
                        @change="() => updateModelTransform('Move')"
                      />
                    </div>

                    <div class="flex items-center gap-1">
                      <label class="text-blue-400 text-[10px] w-3">Y</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.position.y"
                        :step="0.1"
                        :min="-100"
                        :max="100"
                        @update:model-value="(value) => updateModelTransformFast('Move', 'y', value)"
                        @change="() => updateModelTransform('Move')"
                      />
                    </div>

                    <div class="flex items-center gap-1">
                      <label class="text-green-400 text-[10px] w-3">Z</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.position.z"
                        :step="0.1"
                        :min="-100"
                        :max="100"
                        @update:model-value="(value) => updateModelTransformFast('Move', 'z', value)"
                        @change="() => updateModelTransform('Move')"
                      />
                    </div>
                  </div>
                </div>

                <!-- 旋转 -->
                <div class="mb-1">
                  <div class="text-[#909090] text-[10px] mb-0.5">旋转</div>
                  <div class="grid grid-cols-3 gap-1">
                    <div class="flex items-center gap-1">
                      <label class="text-red-400 text-[10px] w-3">X</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.rotation.x"
                        :step="0.1"
                        :min="-360"
                        :max="360"
                        @update:model-value="(value) => updateModelTransformFast('Rotate', 'x', value)"
                        @change="() => updateModelTransform('Rotate')"
                      />
                    </div>

                    <div class="flex items-center gap-1">
                      <label class="text-blue-400 text-[10px] w-3">Y</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.rotation.y"
                        :step="0.1"
                        :min="-360"
                        :max="360"
                        @update:model-value="(value) => updateModelTransformFast('Rotate', 'y', value)"
                        @change="() => updateModelTransform('Rotate')"
                      />
                    </div>

                    <div class="flex items-center gap-1">
                      <label class="text-green-400 text-[10px] w-3">Z</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.rotation.z"
                        :step="0.1"
                        :min="-360"
                        :max="360"
                        @update:model-value="(value) => updateModelTransformFast('Rotate', 'z', value)"
                        @change="() => updateModelTransform('Rotate')"
                      />
                    </div>
                  </div>
                </div>

                <!-- 缩放 -->
                <div>
                  <div class="text-[#909090] text-[10px] mb-0.5">缩放</div>
                  <div class="grid grid-cols-3 gap-1">
                    <div class="flex items-center gap-1">
                      <label class="text-red-400 text-[10px] w-3">X</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.scale.x"
                        :step="0.1"
                        :min="0.01"
                        :max="10"
                        @update:model-value="(value) => updateModelTransformFast('Scale', 'x', value)"
                        @change="() => updateModelTransform('Scale')"
                      />
                    </div>

                    <div class="flex items-center gap-1">
                      <label class="text-blue-400 text-[10px] w-3">Y</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.scale.y"
                        :step="0.1"
                        :min="0.01"
                        :max="10"
                        @update:model-value="(value) => updateModelTransformFast('Scale', 'y', value)"
                        @change="() => updateModelTransform('Scale')"
                      />
                    </div>

                    <div class="flex items-center gap-1">
                      <label class="text-green-400 text-[10px] w-3">Z</label>
                      <NumberInputWithSlider
                        v-model="modelData.defaultTransform.scale.z"
                        :step="0.1"
                        :min="0.01"
                        :max="10"
                        @update:model-value="(value) => updateModelTransformFast('Scale', 'z', value)"
                        @change="() => updateModelTransform('Scale')"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- 碰撞选项 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-orange-600">
                <div class="flex items-center justify-between">
                  <label class="text-[#e0e0e0] font-medium">碰撞</label>
                  <div class="flex items-center space-x-4">
                    <label class="text-[#909090] text-[10px] flex items-center space-x-1">
                      <input
                        v-model="modelData.collision.type"
                        type="radio"
                        value="none"
                        class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b]"
                      />
                      <span>无</span>
                    </label>
                    <label class="text-[#909090] text-[10px] flex items-center space-x-1">
                      <input
                        v-model="modelData.collision.type"
                        type="radio"
                        value="box"
                        class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b]"
                      />
                      <span>包围盒</span>
                    </label>
                    <label class="text-[#909090] text-[10px] flex items-center space-x-1">
                      <input
                        v-model="modelData.collision.type"
                        type="radio"
                        value="mesh"
                        class="rounded bg-[#1a1a1a] border-[#3c3c3c] checked:bg-[#84a65b]"
                      />
                      <span>网格</span>
                    </label>
                  </div>
                </div>
              </div>

              <!-- 物理属性 -->
              <div class="bg-[#3c3c3c]/50 p-2 rounded border-l-2 border-purple-600">
                <label class="text-[#e0e0e0] font-medium block mb-1 text-[10px]">物理</label>
                <!-- 质量 -->
                <div class="mb-1">
                  <div class="text-[#909090] text-[10px] mb-0.5">质量</div>
                  <div class="flex items-center bg-[#1a1a1a] rounded px-1 py-0.5">
                    <NumberInputWithSlider
                      v-model="modelData.mechanics.mass"
                      :step="0.1"
                      :min="0.01"
                      :max="100"
                      @change="() => updateModelMechanics('SetMass')"
                    />
                  </div>
                </div>
                <!-- 弹性系数 -->
                <div class="mb-1">
                  <div class="text-[#909090] text-[10px] mb-0.5">弹性系数</div>
                  <div class="flex items-center bg-[#1a1a1a] rounded px-1 py-0.5">
                    <NumberInputWithSlider
                      v-model="modelData.mechanics.restitution"
                      :step="0.05"
                      :min="0"
                      :max="1"
                      @change="() => updateModelMechanics('SetRestitution')"
                    />
                  </div>
                </div>
                <!-- 阻尼 -->
                <div>
                  <div class="text-[#909090] text-[10px] mb-0.5">阻尼</div>
                  <div class="flex items-center bg-[#1a1a1a] rounded px-1 py-0.5">
                    <NumberInputWithSlider
                      v-model="modelData.mechanics.damping"
                      :step="0.01"
                      :min="0"
                      :max="1"
                      @change="() => updateModelMechanics('SetDamping')"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- 模型 - 积木 -->
            <div v-show="ActiveSubTab === 'Blockly'" style="height: 400px;">
              <BlocklyWorkspace
                v-if="modelData.name"
                :actorName="modelData.name"
                :sceneName="modelData.targetScene || sceneData.name"
                embedded
              />
              <div v-else class="flex items-center justify-center h-full text-[#909090] text-xs">
                请先选中一个物体
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import NumberInputWithSlider from '@/components/ui/NumberInputWithSlider.vue';
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue';
import { useRoute } from 'vue-router';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import BlocklyWorkspace from '@/blockly/components/BlocklyWorkspace.vue';
import { appService, sceneService, projectService } from '@/utils/bridge.js';
import { DEFAULT_SCENE_NAME } from '@/utils/constants.js';
import { useErrorHandler } from '@/composables/useErrorHandler.js';
import { setActorContext } from '@/blockly/composables/useActorContext.js';

const { error: logError, warn: logWarn } = useErrorHandler('Object');

// ========== 防抖工具 ==========
const _debounceTimers = {};
const debounced = (key, fn, delay = 200) => {
  clearTimeout(_debounceTimers[key]);
  _debounceTimers[key] = setTimeout(fn, delay);
};

// ========== 路由参数 ==========
const route = useRoute();

// ========== 主标签页状态 ==========
const mainActiveTab = ref('scene'); // 'scene', 'actor', 'model'
const ActiveSubTab = ref('Basic');

// ========== 标签页定义 ==========
const sceneTabs = [
  { id: 'Basic', label: '基础' },
  { id: 'Terrain', label: '地形' },
  { id: 'Script', label: '脚本' },
];

const actorTabs = [
  { id: 'Basic', label: '基础' },
  { id: 'Model', label: '模型' },
  { id: 'Blockly', label: '积木' },
  { id: 'Script', label: '脚本' },
];

const modelTabs = [
  { id: 'Basic', label: '基础' },
  { id: 'Model', label: '模型' },
  { id: 'Blockly', label: '积木' },
];

// ========== 当前打开的文件 ==========
const currentActorFile = ref('');
const currentModelFile = ref('');

// ========== 场景数据 ==========
const sceneData = ref({
  sceneId: '',
  name: '默认场景',
  activeCameraName: null,
  cameras: [],
  light: {
    enabled: true,
    direction: { x: 1.0, y: 1.0, z: 1.0 },
  },
  terrain: {
    type: 'none',
    path: '',
    size: 10.0,
  },
  grid: {
    enabled: true,
  },
  script: {
    path: '',
  },
});

// ========== 单位数据 ==========
const actorData = ref({
  name: '',
  handle: 0,
  parentScene: '',
  file: '',
  model: {
    path: '',
  },

  hasGeometry: false,
  transform: {
    position: { x: 0.0, y: 0.0, z: 0.0 },
    rotation: { x: 0.0, y: 0.0, z: 0.0 },
    scale: { x: 1.0, y: 1.0, z: 1.0 },
  },
  collision: {
    type: 'none',
  },

  hasMechanics: false,
  mechanics: {
    mass: 1.0,
    restitution: 0.8,
    damping: 0.99,
  },
  script: {
    path: '',
  },
  camera_lock: {
    lock_to_camera: false,
    position_offset: { x: 0.0, y: 0.0, z: 2.0 },
    rotation_offset: { x: 0.0, y: 0.0, z: 0.0 },
  },
});

// ========== 模型数据 ==========
const modelData = ref({
  name: '',
  handle: 0,
  targetScene: '',
  file: '',
  defaultTransform: {
    position: { x: 0.0, y: 0.0, z: 0.0 },
    rotation: { x: 0.0, y: 0.0, z: 0.0 },
    scale: { x: 1.0, y: 1.0, z: 1.0 },
  },
  collision: {
    type: 'none',
  },
  mechanics: {
    mass: 1.0,
    restitution: 0.8,
    damping: 0.99,
  },
});

// ========== 计算属性 ==========
const currentFileInfo = computed(() => {
  if (mainActiveTab.value === 'scene') {
    return `🎬 场景: ${sceneData.value.name}`;
  } else if (mainActiveTab.value === 'actor') {
    const fileName = currentActorFile.value ? actorData.value.name : '未打开';
    return `👤 单位: ${fileName}`;
  } else {
    const fileName = currentModelFile.value ? modelData.value.name : '未打开';
    return `📦 模型: ${fileName}`;
  }
});

// ========== 方法 ==========
const switchMainTab = (tab) => {
  mainActiveTab.value = tab;
  ActiveSubTab.value = 'Basic'; // 重置子标签
};

// 加载场景数据
const loadSceneData = async (sceneId) => {
  if (!sceneId) return;

  try {
    // 调用后端接口获取场景数据
    const result = await sceneService.getScene(sceneId);
    if (result) {
      const data = result.data;

      sceneData.value.sceneId = data.scene_id || data.id || sceneId;
      sceneData.value.name = data.name || sceneId;
      sceneData.value.activeCameraName = data.active_camera_name || null;
      sceneData.value.cameras = Array.isArray(data.cameras) ? data.cameras : [];

      // 加载光照数据
      if (data.sun) {
        sceneData.value.light.enabled = data.sun.enabled !== false;
        sceneData.value.light.direction = {
          x: data.sun.direction?.[0] || 1.0,
          y: data.sun.direction?.[1] || 1.0,
          z: data.sun.direction?.[2] || 1.0,
        };
      }

      // 加载地形数据
      if (data.terrain) {
        sceneData.value.terrain.type = data.terrain.type || 'none';
        sceneData.value.terrain.path = data.terrain.path || '';
        sceneData.value.terrain.size = data.terrain.size || 10.0;
      }

      // 加载网格数据（兼容不同后端字段名）
      if (data.grid && typeof data.grid.enabled === 'boolean') {
        sceneData.value.grid.enabled = data.grid.enabled;
      } else if (typeof data.floor_grid_enabled === 'boolean') {
        sceneData.value.grid.enabled = data.floor_grid_enabled;
      }

      // 加载脚本数据
      sceneData.value.script.path = data.script || '';
    }
  } catch (e) {
    logError('加载场景数据失败', e);
  }
};

// 加载单位数据 - 需要场景ID和单位ID
const loadActorData = async (sceneId, actorId) => {
  if (!actorId) return;

  try {
    // 调用后端接口获取单位数据，传入场景ID和单位ID
    const result = await sceneService.getActor(sceneId, actorId);
    if (result) {
      const data = result.data;
      actorData.value.name = actorId;
      actorData.value.handle = Number(data.handle || 0);
      actorData.value.parentScene = sceneId || '';
      actorData.value.file = data.path;
      actorData.value.model.path = data.model || '';

      if (data.geometry) {
        actorData.value.hasGeometry = true;
        actorData.value.transform.position = {
          x: data.geometry.position?.[0] || 0,
          y: data.geometry.position?.[1] || 0,
          z: data.geometry.position?.[2] || 0,
        };
        actorData.value.transform.rotation = {
          x: data.geometry.rotation?.[0] || 0,
          y: data.geometry.rotation?.[1] || 0,
          z: data.geometry.rotation?.[2] || 0,
        };
        actorData.value.transform.scale = {
          x: data.geometry.scale?.[0] || 1,
          y: data.geometry.scale?.[1] || 1,
          z: data.geometry.scale?.[2] || 1,
        };
      } else {
        actorData.value.hasGeometry = false;
      }

      actorData.value.collision.type = data.collision || 'none';
      actorData.value.script.path = data.script || '';

      // 相机锁定数据
      if (data.camera_lock) {
        actorData.value.camera_lock.lock_to_camera =
          data.camera_lock.lock_to_camera || false;
        actorData.value.camera_lock.position_offset = {
          x: data.camera_lock.position_offset?.[0] || 0,
          y: data.camera_lock.position_offset?.[1] || 0,
          z: data.camera_lock.position_offset?.[2] || 2,
        };
        actorData.value.camera_lock.rotation_offset = {
          x: data.camera_lock.rotation_offset?.[0] || 0,
          y: data.camera_lock.rotation_offset?.[1] || 0,
          z: data.camera_lock.rotation_offset?.[2] || 0,
        };
      }

      if (data.mechanics) {
        actorData.value.hasMechanics = true;
        actorData.value.mechanics.mass = data.mechanics.mass ?? 1.0;
        actorData.value.mechanics.restitution = data.mechanics.restitution ?? 0.8;
        actorData.value.mechanics.damping = data.mechanics.damping ?? 0.99;
      } else {
        actorData.value.hasMechanics = false;
      }
    }
  } catch (e) {
    logError('加载单位数据失败', e);
  }
};

// 加载模型数据 - 需要场景ID和模型ID
const loadModelData = async (sceneId, modelId) => {
  if (!modelId) return;

  try {
    // 调用后端接口获取模型数据，传入场景ID和模型ID
    const result = await sceneService.getActor(sceneId, modelId);
    if (result) {
      const data = result.data;
      modelData.value.name = modelId;
      modelData.value.handle = Number(data.handle || 0);
      modelData.value.targetScene = sceneId || '';
      modelData.value.file = data.path;

      if (data.geometry) {
        modelData.value.defaultTransform.position = {
          x: data.geometry.position?.[0] || 0,
          y: data.geometry.position?.[1] || 0,
          z: data.geometry.position?.[2] || 0,
        };
        modelData.value.defaultTransform.rotation = {
          x: data.geometry.rotation?.[0] || 0,
          y: data.geometry.rotation?.[1] || 0,
          z: data.geometry.rotation?.[2] || 0,
        };
        modelData.value.defaultTransform.scale = {
          x: data.geometry.scale?.[0] || 1,
          y: data.geometry.scale?.[1] || 1,
          z: data.geometry.scale?.[2] || 1,
        };
      }

      modelData.value.collision.type = data.collision || 'none';

      if (data.mechanics) {
        modelData.value.mechanics.mass = data.mechanics.mass ?? 1.0;
        modelData.value.mechanics.restitution = data.mechanics.restitution ?? 0.8;
        modelData.value.mechanics.damping = data.mechanics.damping ?? 0.99;
      }
    }
  } catch (e) {
    logError('加载模型数据失败', e);
  }
};

// 更新光照方向
const updateLightDirection = async () => {
  if (mainActiveTab.value !== 'scene' || !sceneData.value.name) return;

  try {
    // 如果光照启用，发送实际方向值；如果禁用，发送 (0,0,0) 或 (0,-1,0) 等表示无光照
    const direction = {
      x: parseFloat(sceneData.value.light.direction.x),
      y: parseFloat(sceneData.value.light.direction.y),
      z: parseFloat(sceneData.value.light.direction.z),
    };
    await sceneService.sunDirection(
      sceneData.value.sceneId || sceneData.value.name,
      sceneData.value.light.enabled,
      [direction.x, direction.y, direction.z]
    );
  } catch (e) {
    logError('更新光照方向失败', e);
  }
};

const updateFloorGrid = async () => {
  if (mainActiveTab.value !== 'scene' || !sceneData.value.name) return;

  try {
    if (typeof sceneService.floorGrid === 'function') {
      await sceneService.floorGrid(
        sceneData.value.sceneId || sceneData.value.name,
        sceneData.value.grid.enabled
      );
    } else {
      logWarn('sceneService.floorGrid 未定义，暂无法同步网格开关到后端');
    }
  } catch (e) {
    logError('更新网格显示状态失败', e);
  }
};

const ACTOR_TRANSFORM_OPERATION = {
  Move: 0,
  Rotate: 1,
  Scale: 2,
};

const applyAxisOverride = (vector, axis, value) => {
  if (!axis) return vector;
  const axisIndex = { x: 0, y: 1, z: 2 }[axis];
  if (axisIndex === undefined) return vector;
  vector[axisIndex] = Number(value);
  return vector;
};

const getTransformVector = (transform, operationType, axis = null, value = null) => {
  if (!transform) return null;
  switch (operationType) {
    case 'Move':
      return applyAxisOverride(
        [
          Number(transform.position.x),
          Number(transform.position.y),
          Number(transform.position.z),
        ],
        axis,
        value
      );
    case 'Rotate':
      return applyAxisOverride(
        [
          Number(transform.rotation.x),
          Number(transform.rotation.y),
          Number(transform.rotation.z),
        ],
        axis,
        value
      );
    case 'Scale':
      return applyAxisOverride(
        [
          Number(transform.scale.x),
          Number(transform.scale.y),
          Number(transform.scale.z),
        ],
        axis,
        value
      );
    default:
      return null;
  }
};

const getActorTransformVector = (operationType, axis = null, value = null) =>
  getTransformVector(actorData.value.transform, operationType, axis, value);

const getModelTransformVector = (operationType, axis = null, value = null) =>
  getTransformVector(modelData.value.defaultTransform, operationType, axis, value);

const actorTransformFastWarnings = new Set();
const pendingTransformFastUpdates = new Map();
let transformFastRafId = null;

const warnActorTransformFastOnce = (key, message, detail = null) => {
  if (actorTransformFastWarnings.has(key)) return;
  actorTransformFastWarnings.add(key);
  logWarn(message, detail);
};

const flushTransformFastUpdates = () => {
  transformFastRafId = null;
  const updates = Array.from(pendingTransformFastUpdates.values());
  pendingTransformFastUpdates.clear();

  for (const update of updates) {
    try {
      update.bridge.actorTransform(update.handle, update.operation, update.vector);
    } catch (e) {
      logError('V8 更新物体变换失败', e);
    }
  }
};

const queueTransformFastUpdate = (update) => {
  const key = `${update.source}:${update.handle}:${update.operation}`;
  pendingTransformFastUpdates.set(key, update);
  if (transformFastRafId != null) return;
  transformFastRafId = requestAnimationFrame(flushTransformFastUpdates);
};

const updateTransformFast = ({ source, actorName, handle, operationType, axis = null, value = null, vector }) => {
  const operation = ACTOR_TRANSFORM_OPERATION[operationType];
  const bridge = window.coronaBridge;
  if (!handle) {
    warnActorTransformFastOnce(`${source}-missing-handle`, 'ActorTransformFast skipped: actor handle is missing', {
      source,
      actor: actorName,
      handle,
    });
    return;
  }
  if (operation === undefined || !vector) {
    warnActorTransformFastOnce(`${source}-bad-operation`, `ActorTransformFast skipped: invalid operation ${operationType}`, {
      source,
      actor: actorName,
      handle,
    });
    return;
  }
  if (!bridge || typeof bridge.actorTransform !== 'function') {
    warnActorTransformFastOnce(`${source}-missing-bridge`, 'ActorTransformFast skipped: window.coronaBridge.actorTransform is unavailable', {
      source,
      actor: actorName,
      handle,
    });
    return;
  }

  queueTransformFastUpdate({
    source,
    handle,
    operation,
    vector,
    bridge,
  });
};

const updateActorTransformFast = (operationType, axis = null, value = null) => {
  updateTransformFast({
    source: 'actor',
    actorName: currentActorFile.value,
    handle: actorData.value.handle,
    operationType,
    axis,
    value,
    vector: getActorTransformVector(operationType, axis, value),
  });
};

const updateModelTransformFast = (operationType, axis = null, value = null) => {
  updateTransformFast({
    source: 'model',
    actorName: currentModelFile.value,
    handle: modelData.value.handle,
    operationType,
    axis,
    value,
    vector: getModelTransformVector(operationType, axis, value),
  });
};

// 更新单位变换
const updateActorTransform = (operationType) => {
  if (!currentActorFile.value || !actorData.value.parentScene) return;
  debounced(`actor_transform_${operationType}`, async () => {
    try {
      let operation = '';
      const vector = getActorTransformVector(operationType);
      if (!vector) return;

      switch (operationType) {
        case 'Move':
          operation = 'Move';
          break;
        case 'Rotate':
          operation = 'Rotate';
          break;
        case 'Scale':
          operation = 'Scale';
          break;
        default:
          return;
      }

      await sceneService.actorOperation(
        actorData.value.parentScene,
        currentActorFile.value,
        operation,
        vector
      );
    } catch (e) {
      logError('更新单位变换失败', e);
    }
  });
};

// 更新单位物理属性
const updateActorMechanics = (operationType) => {
  if (!currentActorFile.value || !actorData.value.parentScene) return;
  debounced(`actor_mechanics_${operationType}`, async () => {
    try {
      let value = 0;
      switch (operationType) {
        case 'SetMass':
          value = actorData.value.mechanics.mass;
          break;
        case 'SetRestitution':
          value = actorData.value.mechanics.restitution;
          break;
        case 'SetDamping':
          value = actorData.value.mechanics.damping;
          break;
        default:
          return;
      }

      await sceneService.actorOperation(
        actorData.value.parentScene,
        currentActorFile.value,
        operationType,
        [value]
      );
    } catch (e) {
      logError('更新单位物理属性失败', e);
    }
  });
};

// 更新相机锁定
const updateCameraLock = () => {
  if (!currentActorFile.value || !actorData.value.parentScene) return;
  debounced('camera_lock_toggle', async () => {
    try {
      await sceneService.setCameraLock(
        actorData.value.parentScene,
        currentActorFile.value,
        actorData.value.camera_lock.lock_to_camera
      );
    } catch (e) {
      logError('更新相机锁定状态失败', e);
    }
  });
};

const updateCameraLockOffset = () => {
  if (!currentActorFile.value || !actorData.value.parentScene) return;
  if (!actorData.value.camera_lock.lock_to_camera) return;
  debounced('camera_lock_offset', async () => {
    try {
      const offset = [
        Number(actorData.value.camera_lock.position_offset.x),
        Number(actorData.value.camera_lock.position_offset.y),
        Number(actorData.value.camera_lock.position_offset.z),
      ];
      await sceneService.setCameraLockOffset(
        actorData.value.parentScene,
        currentActorFile.value,
        offset
      );
    } catch (e) {
      logError('更新相机位置偏移失败', e);
    }
  });
};

const updateCameraLockRotation = () => {
  if (!currentActorFile.value || !actorData.value.parentScene) return;
  if (!actorData.value.camera_lock.lock_to_camera) return;
  debounced('camera_lock_rotation', async () => {
    try {
      const rotation = [
        Number(actorData.value.camera_lock.rotation_offset.x),
        Number(actorData.value.camera_lock.rotation_offset.y),
        Number(actorData.value.camera_lock.rotation_offset.z),
      ];
      await sceneService.setCameraLockRotation(
        actorData.value.parentScene,
        currentActorFile.value,
        rotation
      );
    } catch (e) {
      logError('更新相机旋转偏移失败', e);
    }
  });
};

// 更新模型变换
const updateModelTransform = (operationType) => {
  if (!currentModelFile.value || !modelData.value.targetScene) return;
  debounced(`model_transform_${operationType}`, async () => {
    try {
      let vector = [];
      let operation = '';

      switch (operationType) {
        case 'Move':
          vector = [
            Number(modelData.value.defaultTransform.position.x),
            Number(modelData.value.defaultTransform.position.y),
            Number(modelData.value.defaultTransform.position.z),
          ];
          operation = 'Move';
          break;
        case 'Rotate':
          vector = [
            Number(modelData.value.defaultTransform.rotation.x),
            Number(modelData.value.defaultTransform.rotation.y),
            Number(modelData.value.defaultTransform.rotation.z),
          ];
          operation = 'Rotate';
          break;
        case 'Scale':
          vector = [
            Number(modelData.value.defaultTransform.scale.x),
            Number(modelData.value.defaultTransform.scale.y),
            Number(modelData.value.defaultTransform.scale.z),
          ];
          operation = 'Scale';
          break;
        default:
          return;
      }

      await sceneService.actorOperation(
        modelData.value.targetScene,
        currentModelFile.value,
        operation,
        vector
      );
    } catch (e) {
      logError('更新模型变换失败', e);
    }
  });
};

// 更新模型物理属性
const updateModelMechanics = (operationType) => {
  if (!currentModelFile.value || !modelData.value.targetScene) return;
  debounced(`model_mechanics_${operationType}`, async () => {
    try {
      let value = 0;
      switch (operationType) {
        case 'SetMass':
          value = modelData.value.mechanics.mass;
          break;
        case 'SetRestitution':
          value = modelData.value.mechanics.restitution;
          break;
        case 'SetDamping':
          value = modelData.value.mechanics.damping;
          break;
        default:
          return;
      }

      await sceneService.actorOperation(
        modelData.value.targetScene,
        currentModelFile.value,
        operationType,
        [value]
      );
    } catch (e) {
      logError('更新模型物理属性失败', e);
    }
  });
};

// 文件选择方法
const selectTerrainFile = async () => {
  try {
    const result = await sceneService.selectModelFileDialog(
      sceneData.value.sceneId || sceneData.value.name,
      '',
      'terrain'
    );
    if (result.success && result.data) {
      sceneData.value.terrain.path = result.data;
    }
  } catch (e) {
    logError('选择地形文件失败', e);
  }
};

const selectSceneScript = async () => {
  try {
    const result = await sceneService.selectModelFileDialog(
      sceneData.value.sceneId || sceneData.value.name,
      '',
      'script'
    );
    if (result.success && result.data) {
      sceneData.value.script.path = result.data;
    }
  } catch (e) {
    logError('选择场景脚本失败', e);
  }
};

const selectModelFile = async () => {
  if (mainActiveTab.value !== 'actor') return;
  try {
    const result = await sceneService.selectModelFileDialog(
      actorData.value.parentScene,
      actorData.value.name,
      'model'
    );
    if (result.success && result.data) {
      actorData.value.model.path = result.data;
    }
  } catch (e) {
    logError('选择模型文件失败', e);
  }
};

const selectActorScript = async () => {
  try {
    const result = await sceneService.selectModelFileDialog(
      actorData.value.parentScene,
      actorData.value.name,
      'script'
    );
    if (result.success && result.data) {
      actorData.value.script.path = result.data;
    }
  } catch (e) {
    logError('选择单位脚本失败', e);
  }
};

const CloseFloat = async () => {
  try {
    await appService.removeDockWidget('SceneDatas');
  } catch (e) {
    logError('关闭 Dock 失败', e);
  }
};

const onBlocklyResize = () => {
  // Blockly调整大小处理
};

// ========== 变换更新回调函数 ==========
const onActorTransformUpdated = (position, rotation, scale) => {
  // 只在当前标签页是 actor 时才更新
  if (mainActiveTab.value !== 'actor') return;

  // 更新 UI 数据
  actorData.value.transform.position = {
    x: position[0],
    y: position[1],
    z: position[2],
  };
  actorData.value.transform.rotation = {
    x: rotation[0],
    y: rotation[1],
    z: rotation[2],
  };
  actorData.value.transform.scale = {
    x: scale[0],
    y: scale[1],
    z: scale[2],
  };
};

const onModelTransformUpdated = (position, rotation, scale) => {
  // 只在当前标签页是 model 时才更新
  if (mainActiveTab.value !== 'model') return;

  modelData.value.defaultTransform.position = {
    x: position[0],
    y: position[1],
    z: position[2],
  };
  modelData.value.defaultTransform.rotation = {
    x: rotation[0],
    y: rotation[1],
    z: rotation[2],
  };
  modelData.value.defaultTransform.scale = {
    x: scale[0],
    y: scale[1],
    z: scale[2],
  };
};

// ========== 事件监听 ==========
const setupWindowListener = () => {
  // 监听文件打开事件
  // 参数: type (scene/actor/model), scene_id, actor_id, old_path (可选，重命名时传入)
  window.onActorChange = async (type, scene_id, actor_id, old_path) => {
    if (!type) return;

    // 判断是否是重命名操作（有old_path参数）
    const isRename = old_path !== undefined;

    if (type === 'scene') {
      // --- 通知积木编辑器：切换了场景，清空 actor 上下文 ---
      setActorContext(scene_id, '');

      // 如果是重命名，检查当前是否正在编辑该文件
      if (isRename) {
        if (old_path === (sceneData.value.sceneId || sceneData.value.name)) {
          await loadSceneData(scene_id);
          ActiveSubTab.value = 'Basic';
        }
      }
      // 打开文件操作，直接切换到场景标签并加载
      else {
        mainActiveTab.value = 'scene';
        await loadSceneData(scene_id);
        ActiveSubTab.value = 'Basic';
      }
    } else if (type === 'actor') {
      // --- 通知积木编辑器：选中了场景中的 Actor ---
      setActorContext(scene_id, actor_id);

      // 如果是重命名，检查当前是否正在编辑该文件
      if (isRename) {
        if (old_path === currentActorFile.value) {
          currentActorFile.value = actor_id;
          await loadActorData(scene_id, actor_id);
          ActiveSubTab.value = 'Basic';
        }
      }
      // 打开文件操作，直接切换到单位标签并加载
      else {
        mainActiveTab.value = 'actor';
        currentActorFile.value = actor_id;
        await loadActorData(scene_id, actor_id);
        ActiveSubTab.value = 'Basic';
      }
    } else if (type === 'model') {
      // 如果是重命名，检查当前是否正在编辑该文件
      if (isRename) {
        if (old_path === currentModelFile.value) {
          currentModelFile.value = actor_id;
          await loadModelData(scene_id, actor_id);
          ActiveSubTab.value = 'Basic';
        }
      }
      // 打开文件操作，直接切换到模型标签并加载
      else {
        mainActiveTab.value = 'model';
        currentModelFile.value = actor_id;
        await loadModelData(scene_id, actor_id);
        ActiveSubTab.value = 'Basic';
      }
    } else {
      // 未知类型（multimedia、mesh、文件扩展名等），按模型处理
      if (!isRename) {
        mainActiveTab.value = 'model';
        currentModelFile.value = actor_id;
        await loadModelData(scene_id, actor_id);
        ActiveSubTab.value = 'Basic';
      }
    }
  };

  // 注册全局回调接收器
  window.onTransformUpdate = (sceneName, actorName, position, rotation, scale, type) => {
    if (
      type === 'actor' &&
      sceneName === actorData.value.parentScene &&
      actorName === actorData.value.name
    ) {
      onActorTransformUpdated(position, rotation, scale);
    } else if (
      type === 'model' &&
      sceneName === modelData.value.targetScene &&
      actorName === modelData.value.name
    ) {
      onModelTransformUpdated(position, rotation, scale);
    }
  };
};

// ========== 生命周期 ==========
onMounted(async () => {
  // 场景默认存在，直接加载场景数据
  const result = await projectService.OnInit();
  await loadSceneData(result.data.path || DEFAULT_SCENE_NAME);

  setupWindowListener();
});

onUnmounted(() => {});
</script>
