import "./globals.css";
import Nav from "../components/Nav";

export const metadata = {
  title: "Swing Desk · 美股短线交易台",
  description: "US stock swing trading — multi-strategy backtest, live paper verification & signals",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{
              var p=new URLSearchParams(location.search).get('theme');
              var t=p||localStorage.getItem('wot-theme')||'dark';
              if(p)localStorage.setItem('wot-theme',p);
              document.documentElement.dataset.theme=t;
            }catch(e){document.documentElement.dataset.theme='dark';}})();`,
          }}
        />
      </head>
      <body>
        <Nav />
        <div className="container">{children}</div>
      </body>
    </html>
  );
}
