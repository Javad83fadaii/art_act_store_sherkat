/**
 * SPA / Persistent Client-Side Navigation Engine for Django
 * Provides seamless 60fps page transitions without bottom navigation bar flicker.
 * Brand color: #AB8C58
 */
(function() {
    'use strict';

    // Prevent double initialization
    if (window.__SPA_NAV_INITIALIZED__) return;
    window.__SPA_NAV_INITIALIZED__ = true;

    // Cache for visited pages to enable 0ms instant back/forward & tab switches
    const pageCache = new Map();
    const MAX_CACHE_SIZE = 12;

    let activeController = null;
    let isNavigating = false;

    // =========================================================================
    // 1. Progress Bar Management
    // =========================================================================
    function getProgressBar() {
        let bar = document.getElementById('page-progress-bar');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'page-progress-bar';
            bar.className = 'fixed top-0 left-0 right-0 h-[2.5px] z-[99999] pointer-events-none transition-all duration-300';
            bar.style.background = 'linear-gradient(90deg, #AB8C58, #E2C48B, #AB8C58)';
            bar.style.width = '0%';
            bar.style.opacity = '0';
            bar.style.boxShadow = '0 0 10px rgba(171, 140, 88, 0.6)';
            document.body.appendChild(bar);
        }
        return bar;
    }

    function startProgress() {
        const bar = getProgressBar();
        bar.style.transition = 'width 0.25s ease-out, opacity 0.15s ease';
        bar.style.opacity = '1';
        bar.style.width = '25%';
        setTimeout(() => {
            if (isNavigating) {
                bar.style.width = '70%';
            }
        }, 120);
    }

    function completeProgress() {
        const bar = getProgressBar();
        bar.style.transition = 'width 0.15s ease-out, opacity 0.2s ease 0.15s';
        bar.style.width = '100%';
        bar.style.opacity = '0';
        setTimeout(() => {
            if (!isNavigating) {
                bar.style.width = '0%';
            }
        }, 350);
    }

    // =========================================================================
    // 2. Bottom Navigation Bar Micro-Interactions & Indicator
    // =========================================================================
    function getBottomNavElements() {
        const navBar = document.getElementById('bottom-nav-bar');
        const navInner = document.getElementById('bottom-nav-inner');
        const indicator = document.getElementById('bottom-nav-indicator');
        const items = navInner ? Array.from(navInner.querySelectorAll('.bottom-nav-item')) : [];
        return { navBar, navInner, indicator, items };
    }

    /**
     * Determines which bottom nav tab corresponds to the given pathname
     */
    function findMatchingTab(pathname, items) {
        if (!items || items.length === 0) return null;

        // Clean trailing slash for uniform matching
        const cleanPath = pathname.replace(/\/+$/, '') || '/';

        // 1. Exact match on data-nav-path
        for (const item of items) {
            const navPath = (item.dataset.navPath || '').replace(/\/+$/, '') || '/';
            if (navPath === cleanPath) {
                return item;
            }
        }

        // 2. Prefix / namespace match
        for (const item of items) {
            const tabKey = item.dataset.navTab;
            if (tabKey === 'auction' && cleanPath.startsWith('/auction')) return item;
            if (tabKey === 'store' && cleanPath.startsWith('/store')) return item;
            if (tabKey === 'profile' && cleanPath.startsWith('/accounts/profile')) return item;
            if (tabKey === 'admin' && (cleanPath.startsWith('/admin-panel') || cleanPath.startsWith('/api/admin'))) return item;
            if (tabKey === 'certificate' && cleanPath.startsWith('/certificate-request')) return item;
            if (tabKey === 'about' && cleanPath.startsWith('/about')) return item;
        }

        return null;
    }

    /**
     * Moves the sliding indicator to the active tab with GPU-accelerated translate3d
     */
    function updateNavIndicator(activeTab, immediate = false) {
        const { navInner, indicator } = getBottomNavElements();
        if (!indicator || !navInner) return;

        if (!activeTab) {
            indicator.style.opacity = '0';
            return;
        }

        const iconWrap = activeTab.querySelector('.bottom-nav-icon-wrap') || activeTab;
        const navRect = navInner.getBoundingClientRect();
        const iconRect = iconWrap.getBoundingClientRect();

        // Calculate exact center coordinates relative to navInner
        const targetX = (iconRect.left - navRect.left) + (iconRect.width - indicator.offsetWidth) / 2;
        const targetY = (iconRect.top - navRect.top) + (iconRect.height - indicator.offsetHeight) / 2;

        const transformValue = `translate3d(${targetX.toFixed(2)}px, ${targetY.toFixed(2)}px, 0)`;

        if (immediate) {
            indicator.style.transition = 'none';
            indicator.style.transform = transformValue;
            indicator.style.opacity = '1';
            // Force browser layout reflow then restore transition
            void indicator.offsetWidth;
            indicator.style.transition = '';
        } else {
            indicator.style.transition = 'transform 0.42s cubic-bezier(0.34, 1.35, 0.64, 1), opacity 0.25s ease';
            indicator.style.transform = transformValue;
            indicator.style.opacity = '1';
        }
    }

    /**
     * Synchronizes active classes and slides the indicator
     */
    function syncBottomNav(pathname = window.location.pathname, immediate = false) {
        const { items } = getBottomNavElements();
        if (items.length === 0) return;

        const activeTab = findMatchingTab(pathname, items);

        items.forEach(item => {
            if (item === activeTab) {
                item.classList.add('is-active');
            } else {
                item.classList.remove('is-active');
            }
        });

        // Use requestAnimationFrame for smooth micro-interaction alignment
        requestAnimationFrame(() => {
            updateNavIndicator(activeTab, immediate);
        });
    }

    // Export sync function globally so other scripts can call it if needed
    window.syncBottomNav = syncBottomNav;

    // =========================================================================
    // 3. Desktop Header Navigation Sync
    // =========================================================================
    function syncHeaderNav(pathname = window.location.pathname) {
        const headerNav = document.querySelector('header nav');
        if (!headerNav) return;

        const links = headerNav.querySelectorAll('a[href]');
        const cleanPath = pathname.replace(/\/+$/, '') || '/';

        links.forEach(link => {
            const href = (link.getAttribute('href') || '').replace(/\/+$/, '') || '/';
            const isActive = (href === cleanPath) ||
                (href.startsWith('/auction') && cleanPath.startsWith('/auction')) ||
                (href.startsWith('/store') && cleanPath.startsWith('/store')) ||
                (href.startsWith('/certificate-request') && cleanPath.startsWith('/certificate-request')) ||
                (href.startsWith('/about') && cleanPath.startsWith('/about'));

            const underline = link.querySelector('span');
            if (isActive) {
                link.classList.add('text-primary');
                link.classList.remove('text-[#2B2A29]', 'dark:text-gray-200');
                if (underline) {
                    underline.classList.remove('w-0');
                    underline.classList.add('w-full');
                }
            } else {
                link.classList.remove('text-primary');
                link.classList.add('text-[#2B2A29]', 'dark:text-gray-200');
                if (underline) {
                    underline.classList.remove('w-full');
                    underline.classList.add('w-0');
                }
            }
        });
    }

    // =========================================================================
    // 4. Script Execution Engine for Swapped Content
    // =========================================================================
    function executeScripts(container) {
        if (!container) return;
        const scripts = container.querySelectorAll('script');

        scripts.forEach(oldScript => {
            // Check script type (skip json templates or non-js)
            const type = (oldScript.type || '').toLowerCase();
            if (type && type !== 'text/javascript' && type !== 'application/javascript' && type !== 'module') {
                return;
            }

            const newScript = document.createElement('script');
            Array.from(oldScript.attributes).forEach(attr => {
                newScript.setAttribute(attr.name, attr.value);
            });

            if (oldScript.src) {
                newScript.src = oldScript.src;
            } else {
                // Wrap inline script in function scope to avoid redeclaration collisions
                newScript.textContent = `(function(){\n${oldScript.textContent}\n})();`;
            }

            oldScript.parentNode.replaceChild(newScript, oldScript);
        });

        // Trigger lifecycle events for page-specific listeners
        try {
            document.dispatchEvent(new CustomEvent('page:loaded', {
                detail: { url: window.location.href }
            }));
            document.dispatchEvent(new Event('DOMContentLoaded'));
            window.dispatchEvent(new Event('resize'));
        } catch (_) {}
    }

    // =========================================================================
    // 5. Client-Side Page Swapping
    // =========================================================================
    async function fetchPage(url, signal) {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-Persistent-Nav': '1',
                'Accept': 'text/html, application/xhtml+xml, application/xml'
            },
            credentials: 'same-origin',
            signal
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const htmlText = await response.text();
        return {
            html: htmlText,
            url: response.url || url,
            redirected: response.redirected
        };
    }

    async function navigate(url, options = {}) {
        const { pushHistory = true, replaceHistory = false } = options;

        // Parse target URL
        const targetUrl = new URL(url, window.location.origin);

        // Abort any ongoing navigation
        if (activeController) {
            activeController.abort();
        }
        activeController = new AbortController();

        isNavigating = true;
        startProgress();

        // Close mobile drawer / sidebar if open
        if (typeof window.toggleMobileMenu === 'function') {
            const sidebar = document.getElementById('mobile-menu-sidebar');
            if (sidebar && !sidebar.classList.contains('translate-x-full')) {
                window.toggleMobileMenu();
            }
        }
        if (typeof window.toggleSearchSidebar === 'function') {
            const searchSidebar = document.getElementById('search-sidebar');
            if (searchSidebar && !searchSidebar.classList.contains('-translate-x-full')) {
                window.toggleSearchSidebar();
            }
        }

        // Optimistic UI update on bottom navigation for instant 0ms tactile feel
        syncBottomNav(targetUrl.pathname, false);
        syncHeaderNav(targetUrl.pathname);

        try {
            let pageData = pageCache.get(targetUrl.href);

            if (!pageData) {
                const res = await fetchPage(targetUrl.href, activeController.signal);
                if (res.redirected && res.url !== targetUrl.href) {
                    // Follow server redirect natively
                    window.location.href = res.url;
                    return;
                }

                const parser = new DOMParser();
                const newDoc = parser.parseFromString(res.html, 'text/html');
                const newMain = newDoc.getElementById('main-content') || newDoc.querySelector('main');

                if (!newMain) {
                    // Target page has different layout (e.g. admin panel or login), fall back natively
                    window.location.href = targetUrl.href;
                    return;
                }

                pageData = {
                    title: newDoc.title || document.title,
                    mainHtml: newMain.innerHTML,
                    mainClass: newMain.className
                };

                // Store in memory cache
                if (pageCache.size >= MAX_CACHE_SIZE) {
                    const firstKey = pageCache.keys().next().value;
                    pageCache.delete(firstKey);
                }
                pageCache.set(targetUrl.href, pageData);
            }

            const currentMain = document.getElementById('main-content') || document.querySelector('main');
            if (!currentMain) {
                window.location.href = targetUrl.href;
                return;
            }

            // Animate out current content smoothly (GPU accelerated transform & opacity)
            currentMain.style.transition = 'opacity 0.14s ease, transform 0.14s ease';
            currentMain.style.opacity = '0';
            currentMain.style.transform = 'translate3d(0, 4px, 0)';

            await new Promise(resolve => setTimeout(resolve, 140));

            // Update page title
            if (pageData.title) {
                document.title = pageData.title;
            }

            // Swap main content
            currentMain.innerHTML = pageData.mainHtml;
            if (pageData.mainClass) {
                currentMain.className = pageData.mainClass;
            }

            // Scroll to top
            window.scrollTo({ top: 0, left: 0, behavior: 'instant' });

            // Animate in new content
            currentMain.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
            currentMain.style.opacity = '1';
            currentMain.style.transform = 'translate3d(0, 0, 0)';

            // Update History API
            if (pushHistory) {
                window.history.pushState({ pjax: true, url: targetUrl.href }, '', targetUrl.href);
            } else if (replaceHistory) {
                window.history.replaceState({ pjax: true, url: targetUrl.href }, '', targetUrl.href);
            }

            // Re-execute scripts within the newly inserted content
            executeScripts(currentMain);

            // Re-sync navigation state in case pathname shifted
            syncBottomNav(window.location.pathname, false);
            syncHeaderNav(window.location.pathname);

        } catch (error) {
            if (error.name === 'AbortError') return;
            console.warn('[SPA Nav] Falling back to standard navigation:', error);
            window.location.href = targetUrl.href;
        } finally {
            isNavigating = false;
            completeProgress();
            activeController = null;
        }
    }

    // =========================================================================
    // 6. Global Link Interception
    // =========================================================================
    function shouldInterceptLink(e, link) {
        if (!link || e.defaultPrevented) return false;
        if (e.button !== 0) return false; // Left click only
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false; // Modifier keys for new tab/window
        if (link.target === '_blank') return false;
        if (link.hasAttribute('download')) return false;

        const href = link.getAttribute('href');
        if (!href || href === '#' || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) {
            return false;
        }

        // Must be same origin
        if (link.origin !== window.location.origin) return false;

        // Ignore explicitly opted-out links or admin paths
        if (link.dataset.native === '1' || link.dataset.noPjax === '1') return false;
        if (link.pathname.startsWith('/admin-panel') || link.pathname.startsWith('/admin/') || link.pathname.startsWith('/api/admin')) {
            return false;
        }

        // Auth logout / login redirects that require full page reload
        if (link.pathname.includes('/logout') || link.pathname.includes('/social/')) {
            return false;
        }

        // Same page with just hash anchor
        if (link.pathname === window.location.pathname && link.search === window.location.search && link.hash) {
            return false;
        }

        return true;
    }

    document.addEventListener('click', function(e) {
        const link = e.target.closest('a');
        if (!shouldInterceptLink(e, link)) return;

        e.preventDefault();
        navigate(link.href, { pushHistory: true });
    }, false);

    // =========================================================================
    // 7. Popstate (Browser Back / Forward Navigation)
    // =========================================================================
    window.addEventListener('popstate', function() {
        navigate(window.location.href, { pushHistory: false });
    });

    // =========================================================================
    // 8. Lifecycle & Window Resize Handling
    // =========================================================================
    let resizeTimer = null;
    window.addEventListener('resize', function() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            syncBottomNav(window.location.pathname, true);
        }, 80);
    });

    window.addEventListener('orientationchange', function() {
        setTimeout(() => {
            syncBottomNav(window.location.pathname, true);
        }, 150);
    });

    // Initial setup on document ready
    function init() {
        syncBottomNav(window.location.pathname, true);
        syncHeaderNav(window.location.pathname);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
