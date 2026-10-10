// JavaScriptがなくてもフォーム送信・ページ移動は利用できます。
document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) return;
    button.hidden = false;
    button.addEventListener('click', () => {
        const visible = input.type === 'password';
        input.type = visible ? 'text' : 'password';
        button.textContent = visible ? '隠す' : '表示';
        button.setAttribute('aria-pressed', String(visible));
        button.setAttribute('aria-label', visible ? 'パスワードを隠す' : 'パスワードを表示する');
    });
});
document.querySelectorAll('[data-dismiss]').forEach((button) => {
    button.addEventListener('click', () => button.closest('.notice').remove());
});
document.querySelectorAll('[data-back-top]').forEach((button) => {
    button.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
        document.querySelector('.brand').focus({ preventScroll: true });
    });
});

// 動きを減らす設定を尊重し、スクロール表示は一度だけ実行する。
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
if ('IntersectionObserver' in window && !motionPreference.matches) {
    const elements = document.querySelectorAll('[data-reveal]');
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.remove('reveal-pending');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.08 });
    elements.forEach((element) => {
        // すでに表示領域にある要素は隠さない。
        if (element.getBoundingClientRect().top >= window.innerHeight) {
            element.classList.add('reveal-pending');
            observer.observe(element);
        }
    });
    motionPreference.addEventListener('change', (event) => {
        if (event.matches) {
            observer.disconnect();
            elements.forEach((element) => element.classList.remove('reveal-pending'));
        }
    });
}
