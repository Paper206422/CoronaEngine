import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import Router from './router/index.js';
import './style.css';
import './blockly/generators/index.js';

const app = createApp(App);
app.use(createPinia());
app.use(Router);
app.mount('#app');
