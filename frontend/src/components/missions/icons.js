// 16px outline icons, 1.5px stroke, one set for the app screens.
const Icon = ({ children }) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;

export const QueueIcon = () => <Icon><path d="M2.5 4h11M2.5 8h11M2.5 12h7" /></Icon>;
export const CallIcon = () => <Icon><path d="M5.2 2.5H3.5a1 1 0 0 0-1 1.1A10 10 0 0 0 12.4 13.5a1 1 0 0 0 1.1-1v-1.7l-2.6-1-1.3 1.3A7 7 0 0 1 5 7.5l1.3-1.3z" /></Icon>;
export const PeopleIcon = () => <Icon><circle cx="6" cy="5.5" r="2.2" /><path d="M2 13c.4-2.2 2-3.4 4-3.4s3.6 1.2 4 3.4" /><path d="M10.5 3.6a2 2 0 0 1 0 3.8M12 9.9c1 .5 1.7 1.5 2 3.1" /></Icon>;
export const ShopIcon = () => <Icon><path d="M2.5 6.5 3.5 3h9l1 3.5M3 6.5v6.5h10V6.5M2.5 6.5h11M6.5 13v-3.5h3V13" /></Icon>;
export const HeadsetIcon = () => <Icon><path d="M3 10V8a5 5 0 0 1 10 0v2" /><path d="M3 10h2v3H3.8a.8.8 0 0 1-.8-.8zM13 10h-2v3h1.2a.8.8 0 0 0 .8-.8zM12 13c0 1-1.2 1.5-3 1.5" /></Icon>;
export const MenuIcon =() => <Icon><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></Icon>;
