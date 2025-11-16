document.addEventListener('DOMContentLoaded', () => {
  const menuToggle = document.getElementById('mobile-menu-toggle');
  if (!menuToggle) return;

  const menuClose = document.getElementById('mobile-menu-close');
  const mobileMenu = document.getElementById('mobile-menu');
  const mobileMenuOverlay = document.getElementById('mobile-menu-overlay');

  const sidebarClose = document.getElementById('mobile-sidebar-close');
  const mobileSidebar = document.getElementById('mobile-sidebar');
  const mobileSidebarOverlay = document.getElementById('mobile-sidebar-overlay');

  const isAuthenticated = menuToggle.dataset.isAuthenticated === 'true';

  function openMenu() {
    if (isAuthenticated && mobileSidebar && mobileSidebarOverlay) {
      mobileSidebar.classList.remove('hidden');
      mobileSidebarOverlay.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      if (mobileMenu) mobileMenu.classList.add('hidden');
      if (mobileMenuOverlay) mobileMenuOverlay.classList.add('hidden');
    } else if (mobileMenu && mobileMenuOverlay) {
      mobileMenu.classList.remove('hidden');
      mobileMenuOverlay.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      if (mobileSidebar) mobileSidebar.classList.add('hidden');
      if (mobileSidebarOverlay) mobileSidebarOverlay.classList.add('hidden');
    }
  }

  function closeMenu() {
    [mobileMenu, mobileSidebar].forEach(el => el?.classList.add('hidden'));
    [mobileMenuOverlay, mobileSidebarOverlay].forEach(el => el?.classList.add('hidden'));
    document.body.style.overflow = '';
  }

  menuToggle.addEventListener('click', openMenu);
  menuClose?.addEventListener('click', closeMenu);
  sidebarClose?.addEventListener('click', closeMenu);
  mobileMenuOverlay?.addEventListener('click', closeMenu);
  mobileSidebarOverlay?.addEventListener('click', closeMenu);

  window.addEventListener('resize', () => {
    if (window.innerWidth >= 768) closeMenu();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeMenu();
  });
});