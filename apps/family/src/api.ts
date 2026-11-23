import axios from 'axios';

const http = axios.create({ baseURL: '/api', timeout: 30000 });

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('nh_family_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (res) => res.data,
  (err) => Promise.reject(err.response?.data?.message || err.message),
);

export default http;
