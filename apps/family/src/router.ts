import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('./views/Login.vue') },
    {
      path: '/',
      component: () => import('./layouts/Shell.vue'),
      children: [
        { path: '', redirect: '/home' },
        { path: 'home', component: () => import('./views/Home.vue') },
        { path: 'tour', component: () => import('./views/Tour.vue') },
        { path: 'bills', component: () => import('./views/Bills.vue') },
        { path: 'meals', component: () => import('./views/Meals.vue') },
        { path: 'care', component: () => import('./views/CareTasks.vue') },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const token = localStorage.getItem('nh_family_token');
  const publicPaths = ['/login', '/tour'];
  if (!publicPaths.includes(to.path) && !token) return '/login';
  if (to.path === '/login' && token) return '/home';
});

export default router;
