import * as Blockly from 'blockly/core';

export const defineDetectBlocks = () => {
  Blockly.Blocks['detect_touch'] = {
    init: function () {
      this.setStyle('detect_blocks');
      this.appendDummyInput()
        .appendField('碰到')
        .appendField(new Blockly.FieldTextInput(''), 'x');
      this.setOutput(true, 'Boolean'); // 设置输出为布尔值
      this.setInputsInline(true);
      this.setHelpUrl('');
      this.setTooltip('检测该按钮是否被按下，返回true或false');
    },
  };

  Blockly.Blocks['detect_distance'] = {
    init: function () {
      this.appendDummyInput()
        .appendField('到')
        .appendField(new Blockly.FieldTextInput(''), 'x')
        .appendField('的距离');
      this.setOutput(true, 'Number');
      this.setStyle('detect_blocks');
    },
  };

  Blockly.Blocks['detect_ask'] = {
    init: function () {
      this.appendDummyInput()
        .appendField('询问')
        .appendField(new Blockly.FieldTextInput(''), 'x')
        .appendField('并等待');
      this.setInputsInline(true);
      this.setPreviousStatement(true, null);
      this.setNextStatement(true, null);
      this.setStyle('detect_blocks');
      this.setHelpUrl('');
    },
  };

  Blockly.Blocks['detect_keyboard1'] = {
    init: function () {
      this.appendDummyInput()
        .appendField('按下')
        .appendField(new Blockly.FieldTextInput(''), 'x')
        .appendField('？');
      this.setOutput(true, 'Boolean'); // 设置输出为布尔值
      this.setInputsInline(true);
      this.setStyle('detect_blocks');
      this.setHelpUrl('');
      this.setTooltip('检测该按键是否被按下，返回true或false');
    },
  };

  Blockly.Blocks['detect_keyboard0'] = {
    init: function () {
      this.appendDummyInput()
        .appendField('松开')
        .appendField(new Blockly.FieldTextInput(''), 'x')
        .appendField('？');
      this.setOutput(true, 'Boolean'); // 设置输出为布尔值
      this.setInputsInline(true);
      this.setStyle('detect_blocks');
      this.setHelpUrl('');
      this.setTooltip('检测该按键是否被松开，返回true或false');
    },
  };

  Blockly.Blocks['detect_mouse1'] = {
    init: function () {
      this.appendDummyInput().appendField('按下鼠标？');
      this.setOutput(true, 'Boolean'); // 设置输出为布尔值
      this.setInputsInline(true);
      this.setStyle('detect_blocks');
      this.setHelpUrl('');
      this.setTooltip('检测鼠标是否被按下，返回true或false');
    },
  };

  Blockly.Blocks['detect_mouse0'] = {
    init: function () {
      this.appendDummyInput().appendField('松开鼠标？');
      this.setOutput(true, 'Boolean'); // 设置输出为布尔值
      this.setInputsInline(true);
      this.setStyle('detect_blocks');
      this.setHelpUrl('');
      this.setTooltip('检测鼠标是否被松开，返回true或false');
    },
  };

  const detectAttribute = [
    ['动画名称', 'NAME'],
    ['动画编号', 'ID'],
    ['X坐标', 'X'],
    ['Y坐标', 'Y'],
    ['Z坐标', 'Z'],
    ['方向', 'DIRECTION'],
    ['大小', 'SIZE'],
  ];
  Blockly.Blocks['detect_attribute'] = {
    init: function () {
      this.appendDummyInput().appendField(new Blockly.FieldDropdown(detectAttribute), 'x');
      this.setInputsInline(true);
      this.setOutput(true, 'Number');
      this.setStyle('detect_blocks');
      this.setTooltip('检测指定的属性');
    },
  };
};
