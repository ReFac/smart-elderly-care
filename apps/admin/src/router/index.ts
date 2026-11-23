import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import Layout from '../layouts/MainLayout.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/Login.vue') },
    {
      path: '/',
      component: Layout,
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: () => import('../views/Dashboard.vue') },
        { path: 'beds', component: () => import('../views/Beds.vue') },
        { path: 'elders', component: () => import('../views/Elders.vue') },
        { path: 'elders/:id', component: () => import('../views/ElderDetail.vue') },
        { path: 'care', component: () => import('../views/Care.vue') },
        { path: 'billing', component: () => import('../views/Billing.vue') },
        { path: 'meals', component: () => import('../views/Meals.vue') },
        { path: 'settings', component: () => import('../views/Settings.vue') },
        { path: 'medical', component: () => import('../views/Placeholder.vue'), props: { title: '医护健康', module: 'medical' } },
        { path: 'ltc', component: () => import('../views/Placeholder.vue'), props: { title: '长护险', module: 'ltc' } },
        { path: 'inventory', component: () => import('../views/Placeholder.vue'), props: { title: '后勤物资', module: 'inventory' } },
        { path: 'hr', component: () => import('../views/Placeholder.vue'), props: { title: '人事排班', module: 'hr' } },
        { path: 'security', component: () => import('../views/Placeholder.vue'), props: { title: '安防告警', module: 'security' } },
        { path: 'reports', component: () => import('../views/Placeholder.vue'), props: { title: '报表报送', module: 'reports' } },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.path !== '/login' && !auth.isLoggedIn) return '/login';
  if (to.path === '/login' && auth.isLoggedIn) return '/dashboard';
});

export default router;
