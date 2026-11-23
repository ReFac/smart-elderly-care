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
        { path: 'medical', component: () => import('../views/Medical.vue') },
        { path: 'ltc', component: () => import('../views/Ltc.vue') },
        { path: 'inventory', component: () => import('../views/Inventory.vue') },
        { path: 'hr', component: () => import('../views/Hr.vue') },
        { path: 'security', component: () => import('../views/Security.vue') },
        { path: 'reports', component: () => import('../views/Reports.vue') },
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
