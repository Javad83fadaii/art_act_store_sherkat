/**
 * Application Core JavaScript
 * Handles global functionality like Toasts, Dark Mode, Gallery, etc.
 */

// Toast Notification System
const Toast = (function() {
    const queue = {
        'top-right': [],
        'top-left': [],
        'bottom-right': [],
        'bottom-left': []
    };

    const containers = {};

    function createContainer(position) {
        if (containers[position]) return containers[position];

        const container = document.createElement('div');
        container.className = `toast-container toast-${position}`;
        // Basic styles are in components.css, but we ensure positioning here if missing
        container.style.position = 'fixed';
        container.style.zIndex = '9999';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.gap = '10px';
        container.style.pointerEvents = 'none';

        if (position === 'top-right') { container.style.top = '20px'; container.style.right = '20px'; }
        if (position === 'top-left') { container.style.top = '20px'; container.style.left = '20px'; }
        if (position === 'bottom-right') { container.style.bottom = '20px'; container.style.right = '20px'; }
        if (position === 'bottom-left') { container.style.bottom = '20px'; container.style.left = '20px'; }

        document.body.appendChild(container);
        containers[position] = container;
        return container;
    }

    function show(message, type = 'success', position = 'bottom-right', durationOrOptions = 5000, maybeOptions = null) {
        const container = createContainer(position);
        const duration = 5000;
        let options = {};
        if (durationOrOptions && typeof durationOrOptions === 'object') {
            options = durationOrOptions;
        } else if (maybeOptions && typeof maybeOptions === 'object') {
            options = maybeOptions;
        }
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type} transform transition-all duration-300 translate-y-2 opacity-0`;
        toast.style.position = 'relative';
        toast.style.overflow = 'hidden';
        
        // Styles should be in components.css, but adding inline for robustness
        toast.style.padding = '12px 24px';
        toast.style.borderRadius = '8px';
        toast.style.color = '#fff';
        toast.style.fontWeight = '500';
        toast.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
        toast.style.pointerEvents = 'auto';
        toast.style.minWidth = '300px';
        toast.style.display = 'flex';
        toast.style.alignItems = 'center';
        toast.style.gap = '8px';
        
        // Colors based on type
        if (type === 'success') toast.style.backgroundColor = '#28a745'; // Green
        else if (type === 'error') toast.style.backgroundColor = '#EF4444'; // Red
        else if (type === 'info') toast.style.backgroundColor = '#3B82F6'; // Blue
        else if (type === 'warning') toast.style.backgroundColor = '#F59E0B'; // Amber
        else toast.style.backgroundColor = '#333';

        // Icon
        let icon = '';
        if (type === 'success') icon = 'check';
        else if (type === 'error') icon = 'error';
        else if (type === 'info') icon = 'info';
        else if (type === 'warning') icon = 'warning';

        const iconEl = document.createElement('span');
        iconEl.className = 'material-symbols-outlined text-[20px]';
        iconEl.textContent = icon;

        const messageEl = document.createElement('span');
        messageEl.style.flex = '1';
        messageEl.textContent = String(message ?? '');

        toast.appendChild(iconEl);
        toast.appendChild(messageEl);

        const actionLabel = options.actionLabel ? String(options.actionLabel) : '';
        const actionHref = options.actionHref ? String(options.actionHref) : '';
        const onAction = typeof options.onAction === 'function' ? options.onAction : null;

        if (actionLabel) {
            const actionEl = document.createElement(actionHref ? 'a' : 'button');
            actionEl.textContent = actionLabel;
            actionEl.style.marginRight = '12px';
            actionEl.style.marginLeft = 'auto';
            actionEl.style.padding = '6px 10px';
            actionEl.style.borderRadius = '8px';
            actionEl.style.fontSize = '12px';
            actionEl.style.fontWeight = '700';
            actionEl.style.background = 'rgba(255, 255, 255, 0.18)';
            actionEl.style.border = '1px solid rgba(255, 255, 255, 0.28)';
            actionEl.style.color = '#fff';
            actionEl.style.cursor = 'pointer';
            actionEl.style.pointerEvents = 'auto';
            actionEl.style.textDecoration = 'none';

            if (actionHref) {
                actionEl.href = actionHref;
            } else {
                actionEl.type = 'button';
            }

            actionEl.addEventListener('click', (e) => {
                e.stopPropagation();
                if (onAction) onAction();
            });

            toast.appendChild(actionEl);
        }

        const progress = document.createElement('div');
        progress.style.position = 'absolute';
        progress.style.left = '0';
        progress.style.right = '0';
        progress.style.bottom = '0';
        progress.style.height = '3px';
        progress.style.background = 'rgba(255, 255, 255, 0.35)';
        progress.style.transformOrigin = 'right center';
        progress.style.transform = 'scaleX(1)';
        progress.style.transition = `transform ${duration}ms linear`;
        toast.appendChild(progress);

        // Add to container
        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.classList.remove('translate-y-2', 'opacity-0');
            requestAnimationFrame(() => {
                progress.style.transform = 'scaleX(0)';
            });
        });

        // Auto remove
        setTimeout(() => {
            toast.classList.add('opacity-0', 'translate-y-2'); // Fade out
            toast.addEventListener('transitionend', () => {
                toast.remove();
            });
        }, duration);
    }

    return { show };
})();

// Expose to window
window.showToast = Toast.show;

document.addEventListener('DOMContentLoaded', () => {
    try {
        const q = new URLSearchParams(window.location.search);
        const message = q.get('toast_message');
        if (!message) return;
        const type = q.get('toast_type') || 'info';
        const position = q.get('toast_position') || 'bottom-left';
        const actionLabel = q.get('toast_action_label') || '';
        const actionHref = q.get('toast_action_href') || '';
        if (window.showToast) {
            window.showToast(message, type, position, { actionLabel, actionHref });
        }
        q.delete('toast_message');
        q.delete('toast_type');
        q.delete('toast_position');
        q.delete('toast_action_label');
        q.delete('toast_action_href');
        const next = q.toString();
        const url = window.location.pathname + (next ? `?${next}` : '') + window.location.hash;
        window.history.replaceState({}, document.title, url);
    } catch (e) {}
});

// Auction Timer Logic
class AuctionTimer {
    constructor(elementOrId, endTimeStr) {
        if (typeof elementOrId === 'string') {
            this.element = document.getElementById(elementOrId);
        } else {
            this.element = elementOrId;
        }
        this.endTime = this.parseTime(endTimeStr);
        this.interval = null;
    }

    parseTime(timeStr) {
        // Assuming timeStr is "HH:MM:SS" representing duration remaining
        const parts = timeStr.split(':').map(Number);
        const now = new Date();
        const end = new Date(now.getTime() + (parts[0] * 3600000) + (parts[1] * 60000) + (parts[2] * 1000));
        return end;
    }

    start() {
        if (!this.element) return;
        this.update();
        this.interval = setInterval(() => this.update(), 1000);
    }

    update() {
        const now = new Date();
        const diff = this.endTime - now;

        if (diff <= 0) {
            clearInterval(this.interval);
            this.element.textContent = "00:00:00";
            this.element.classList.add('text-red-500');
            return;
        }

        const hours = Math.floor(diff / (1000 * 60 * 60));
        const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((diff % (1000 * 60)) / 1000);

        const hStr = hours.toString().padStart(2, '0');
        const mStr = minutes.toString().padStart(2, '0');
        const sStr = seconds.toString().padStart(2, '0');

        this.element.textContent = `${hStr}:${mStr}:${sStr}`;
    }
}

// 360 Viewer Logic
class ThreeSixtyViewer {
    constructor(containerId, images) {
        this.container = document.getElementById(containerId);
        this.display = this.container ? this.container.querySelector('img') : null;
        this.images = images;
        this.totalFrames = images.length;
        this.currentFrame = 0;
        this.isDragging = false;
        this.startX = 0;
        this.lastX = 0;
        
        this.init();
    }
    
    init() {
        if (!this.container || !this.display) return;
        
        // Mouse Events
        this.container.addEventListener('mousedown', (e) => this.startDrag(e.clientX));
        window.addEventListener('mousemove', (e) => this.onDrag(e.clientX));
        window.addEventListener('mouseup', () => this.stopDrag());
        
        // Touch Events
        this.container.addEventListener('touchstart', (e) => this.startDrag(e.touches[0].clientX));
        window.addEventListener('touchmove', (e) => this.onDrag(e.touches[0].clientX));
        window.addEventListener('touchend', () => this.stopDrag());
        
        // Prevent default drag behavior on image
        this.display.addEventListener('dragstart', (e) => e.preventDefault());
    }
    
    startDrag(x) {
        this.isDragging = true;
        this.startX = x;
        this.lastX = x;
        this.container.style.cursor = 'grabbing';
    }
    
    stopDrag() {
        this.isDragging = false;
        this.container.style.cursor = 'grab';
    }
    
    onDrag(x) {
        if (!this.isDragging) return;
        
        const delta = x - this.lastX;
        // Sensitivity: change frame every 10 pixels
        if (Math.abs(delta) > 10) {
            const direction = delta > 0 ? -1 : 1; // Drag right -> rotate left (prev frames), Drag left -> rotate right (next frames)
            this.updateFrame(direction);
            this.lastX = x;
        }
    }
    
    updateFrame(direction) {
        this.currentFrame = (this.currentFrame + direction + this.totalFrames) % this.totalFrames;
        
        if (this.images[this.currentFrame]) {
            this.display.src = this.images[this.currentFrame];
        }

        // For demo purposes, since images are identical, we log
        // console.log(`Showing frame ${this.currentFrame}`);
    }
}

// Gallery Logic
function initGallery() {
    const mainImage = document.getElementById('product-main-image');
    if (!mainImage) return;

    const thumbnails = document.querySelectorAll('[id^="product-thumb-"]');
    thumbnails.forEach(thumb => {
        // Find the parent button or use the div itself if it has the click listener (structure depends on HTML)
        // In the HTML provided: <button class="..."><div id="product-thumb-1" ...></div></button>
        // We should attach listener to the clickable element.
        
        const wrapper = thumb.closest('button') || thumb;
        
        wrapper.addEventListener('click', function() {
            // Get the background image url from the thumbnail
            const thumbStyle = thumb.getAttribute('style'); // background-image: url(...)
            const thumbUrlMatch = thumbStyle.match(/url\(['"]?(.*?)['"]?\)/);
            
            if (thumbUrlMatch && thumbUrlMatch[1]) {
                const newUrl = thumbUrlMatch[1];
                
                // Update main image with fade effect
                mainImage.style.opacity = '0';
                
                setTimeout(() => {
                    mainImage.style.backgroundImage = `url('${newUrl}')`;
                    mainImage.style.opacity = '1';
                }, 200); // Wait for fade out
            }

            // Update active state style (optional, if we want to highlight selected thumb)
            thumbnails.forEach(t => {
                const w = t.closest('button');
                if(w) {
                    w.classList.remove('border-primary');
                    w.classList.add('border-transparent');
                }
            });
            wrapper.classList.remove('border-transparent');
            wrapper.classList.add('border-primary');
        });
    });
}

// Initialize global logic
document.addEventListener('DOMContentLoaded', () => {
    // Check for single auction timer (product page)
    const auctionTimeElement = document.getElementById('auction-timeleft');
    if (auctionTimeElement) {
        const initialTime = auctionTimeElement.textContent.trim(); 
        if (/^\d{2}:\d{2}:\d{2}$/.test(initialTime)) {
            const timer = new AuctionTimer(auctionTimeElement, initialTime);
            timer.start();
        }
    }

    // Check for multiple auction timers (auction list page)
    const auctionTimerElements = document.querySelectorAll('.auction-timer-display');
    auctionTimerElements.forEach(el => {
        const initialTime = el.textContent.trim();
        if (/^\d{2}:\d{2}:\d{2}$/.test(initialTime)) {
            const timer = new AuctionTimer(el, initialTime);
            timer.start();
        }
    });

    // Initialize Gallery
    initGallery();
    
    // Initialize 360 View Switcher
    window.switchView = function(viewType) {
        const mainImage = document.getElementById('product-main-image');
        const view360 = document.getElementById('product-360-view');
        const btnImage = document.getElementById('btn-view-image');
        const btn360 = document.getElementById('btn-view-360');
        const zoomHint = document.getElementById('zoom-hint');

        if (!mainImage || !view360) return;

        if (viewType === 'image') {
            mainImage.classList.remove('hidden');
            view360.classList.add('hidden');
            view360.classList.remove('flex');
            if (zoomHint) zoomHint.classList.remove('hidden');
            
            if (btnImage) {
                btnImage.classList.add('text-primary', 'ring-2', 'ring-primary');
                btnImage.classList.remove('text-neutral-600');
            }
            if (btn360) {
                btn360.classList.remove('text-primary', 'ring-2', 'ring-primary');
                btn360.classList.add('text-neutral-600');
            }
        } else {
            mainImage.classList.add('hidden');
            view360.classList.remove('hidden');
            view360.classList.add('flex');
            if (zoomHint) zoomHint.classList.add('hidden');
            
            if (btn360) {
                btn360.classList.add('text-primary', 'ring-2', 'ring-primary');
                btn360.classList.remove('text-neutral-600');
            }
            if (btnImage) {
                btnImage.classList.remove('text-primary', 'ring-2', 'ring-primary');
                btnImage.classList.add('text-neutral-600');
            }
            
            const modelViewer = view360.querySelector('model-viewer');
            if (modelViewer) {
                return;
            }

            // Initialize 360 viewer if not already done
            if (!window.threeSixtyInstance) {
                 const mainImgUrl = mainImage.style.backgroundImage.slice(5, -2).replace(/['"]/g, "");
                 // Create a fake array of "frames" (36 frames)
                 // In a real implementation, these would be separate URLs: img_1.jpg, img_2.jpg, ...
                 const frames = Array(36).fill(mainImgUrl); 
                 window.threeSixtyInstance = new ThreeSixtyViewer('product-360-view', frames);
            }
        }
    };

    // Bid Manager Placeholder (Live Bidding Simulation)
    function initLiveBidding() {
        const lastBidElement = document.getElementById('auction-lastbid');
        const bidCountElement = document.getElementById('auction-bid-count');
        const suggestedElement = document.getElementById('auction-suggested');
        
        if (!lastBidElement) return;

        // Simulate live updates
        // In a real app, this would be a WebSocket connection
        // setInterval(() => {
        //     // Randomly decide if a new bid comes in (10% chance every 5 seconds)
        //     if (Math.random() > 0.9) {
        //         // Parse current bid
        //         let currentBid = parseInt(lastBidElement.textContent.replace(/,/g, ''));
        //         // Increase by 5-15%
        //         const increase = Math.floor(currentBid * (0.05 + Math.random() * 0.1));
        //         const newBid = currentBid + increase;
                
        //         // Update DOM
        //         lastBidElement.textContent = newBid.toLocaleString();
                
        //         // Update count
        //         if (bidCountElement) {
        //             const currentCount = parseInt(bidCountElement.textContent.match(/\d+/)[0]);
        //             bidCountElement.textContent = `آخرین پیشنهاد (${(currentCount + 1).toLocaleString()} بید)`;
        //         }
                
        //         // Update suggested bid (next minimum bid)
        //         if (suggestedElement) {
        //             const nextMinBid = Math.floor(newBid * 1.05);
        //             suggestedElement.textContent = `${nextMinBid.toLocaleString()} دلار`;
        //         }

        //         // Show notification
        //         window.showToast(`پیشنهاد جدید: ${newBid.toLocaleString()} دلار`, 'info', 'bottom-left');
                
        //         // Flash effect
        //         lastBidElement.classList.add('text-green-600');
        //         setTimeout(() => lastBidElement.classList.remove('text-green-600'), 1000);
        //     }
        // }, 5000);
        
        console.log("Live bidding system initialized (Simulation ready)");
    }

    initLiveBidding();
});
/* =====================
   MOBILE MENU LOGIC
===================== */
document.addEventListener('DOMContentLoaded', () => {
    const menuBtn = document.getElementById('mobile-menu-btn');
    const closeBtn = document.getElementById('close-menu-btn');
    const menuOverlay = document.getElementById('mobile-menu-overlay');
    const menuSidebar = document.getElementById('mobile-menu-sidebar');

    function openMenu() {
        if (menuOverlay && menuSidebar) {
            menuOverlay.classList.remove('hidden'); // حذف کلاس hidden برای نمایش اولیه
            // یک تأخیر کوتاه برای اعمال انیمیشن opacity
            setTimeout(() => {
                menuOverlay.classList.add('open');
                menuSidebar.classList.add('open');
            }, 10);
            document.body.style.overflow = 'hidden'; // جلوگیری از اسکرول صفحه اصلی
        }
    }

    function closeMenu() {
        if (menuOverlay && menuSidebar) {
            menuOverlay.classList.remove('open');
            menuSidebar.classList.remove('open');

            // صبر می‌کنیم انیمیشن تمام شود سپس hidden می‌کنیم
            setTimeout(() => {
                menuOverlay.classList.add('hidden');
            }, 300);

            document.body.style.overflow = ''; // فعال کردن مجدد اسکرول
        }
    }

    // رویداد کلیک برای باز کردن
    if (menuBtn) {
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openMenu();
        });
    }

    // رویداد کلیک برای بستن (دکمه ضربدر)
    if (closeBtn) {
        closeBtn.addEventListener('click', closeMenu);
    }

    // بستن منو با کلیک روی فضای خالی (Overlay)
    if (menuOverlay) {
        menuOverlay.addEventListener('click', closeMenu);
    }
});

window.openMenu = function() {
    const menu = document.getElementById('side-menu');
    const overlay = document.getElementById('menu-overlay');
    if (!menu || !overlay) return;

    overlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
        menu.classList.remove('translate-x-full');
    });
    document.body.style.overflow = 'hidden';
};

window.closeMenu = function() {
    const menu = document.getElementById('side-menu');
    const overlay = document.getElementById('menu-overlay');
    if (!menu || !overlay) return;

    overlay.classList.add('opacity-0');
    menu.classList.add('translate-x-full');
    setTimeout(() => {
        overlay.classList.add('hidden');
        document.body.style.overflow = '';
    }, 300);
};

window.toggleProfileSubmenu = function() {
    const submenu = document.getElementById('profile-submenu');
    const icon = document.getElementById('submenu-icon');
    if (!submenu) return;

    const isHidden = submenu.classList.contains('hidden');
    if (isHidden) {
        submenu.classList.remove('hidden');
        if (icon) icon.classList.add('rotate-180');
    } else {
        submenu.classList.add('hidden');
        if (icon) icon.classList.remove('rotate-180');
    }
};

window.openBidModal = function(triggerEl) {
    const modal = document.getElementById('bid-modal');
    const backdrop = document.getElementById('modal-backdrop-bid');
    const content = document.getElementById('modal-content-bid');
    const form = document.getElementById('bid-form');
    const amountInput = document.getElementById('bid-amount');
    const minNextEl = document.getElementById('bid-min-next');

    if (!modal || !backdrop || !content) return;

    const action = triggerEl?.dataset?.bidAction || '';
    const minNextRaw = triggerEl?.dataset?.minNext || '';

    if (form && action) form.setAttribute('action', action);

    if (minNextEl) {
        const parsed = Number(String(minNextRaw).replace(/,/g, ''));
        minNextEl.textContent = Number.isFinite(parsed) && parsed > 0 ? `حداقل پیشنهاد بعدی: ${parsed.toLocaleString('fa-IR')} دلار` : '';
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => {
        backdrop.classList.remove('opacity-0');
        content.classList.remove('opacity-0', 'scale-90');
        content.classList.add('scale-100');
    });
    document.body.style.overflow = 'hidden';
    if (amountInput) {
        amountInput.value = '';
        amountInput.focus();
    }
};

window.closeModal = function() {
    const modal = document.getElementById('bid-modal');
    const backdrop = document.getElementById('modal-backdrop-bid');
    const content = document.getElementById('modal-content-bid');
    if (!modal || !backdrop || !content) return;

    backdrop.classList.add('opacity-0');
    content.classList.add('opacity-0', 'scale-90');
    content.classList.remove('scale-100');

    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = '';
    }, 300);
};

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (typeof window.closeModal === 'function') window.closeModal();
        if (typeof window.closeMenu === 'function') window.closeMenu();
    }
});
