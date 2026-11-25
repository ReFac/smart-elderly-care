import { faqDirectory } from './features/faq.js';
import { publicPage } from './public-site.js';

const initial = new URLSearchParams(location.search).get('item');
document.getElementById('faq-main').append(faqDirectory({ initial, standalone: true }));
publicPage('常见问题');
