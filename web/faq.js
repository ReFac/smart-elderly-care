import { faqDirectory } from './features/faq.js';
import { colorModeControl } from './lib/color-mode.js';

const initial = new URLSearchParams(location.search).get('item');
document.getElementById('faq-main').append(faqDirectory({ initial, standalone: true }));
document.querySelector('.faq-public-actions').prepend(colorModeControl());
