import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import http from '../api/http';

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('nh_token') || '');
  const user = ref<any>(JSON.parse(localStorage.getItem('nh_user') || 'null'));

  const isLoggedIn = computed(() => !!token.value);

  async function login(username: string, password: string) {
    const res: any = await http.post('/auth/login', { username, password });
    token.value = res.accessToken;
    user.value = res.user;
    localStorage.setItem('nh_token', token.value);
    localStorage.setItem('nh_user', JSON.stringify(user.value));
  }

  function logout() {
    token.value = '';
    user.value = null;
    localStorage.removeItem('nh_token');
    localStorage.removeItem('nh_user');
  }

  return { token, user, isLoggedIn, login, logout };
});
