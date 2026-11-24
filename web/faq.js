import { faqDirectory } from './features/faq.js';

const initial = new URLSearchParams(location.search).get('item');
document.getElementById('faq-main').append(faqDirectory({ initial, standalone: true }));
