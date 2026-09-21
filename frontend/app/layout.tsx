import './globals.css';
import type {Metadata} from 'next';
export const metadata:Metadata={title:'Method — Research workspace',description:'Private owner research dashboard',robots:{index:false,follow:false}};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
