import { Routes, Route } from 'react-router-dom';
import { AppLayout } from '@/components/layout/AppLayout';
import { ProductProvider } from '@/context/ProductContext';
import { Dashboard } from '@/pages/Dashboard';
import { Products } from '@/pages/Products';
import { AddProduct } from '@/pages/AddProduct';
import { ProductDetail } from '@/pages/ProductDetail';
import { Pending } from '@/pages/Pending';
import { Settings } from '@/pages/Settings';
import { ImportProducts } from '@/pages/ImportProducts';
import { PreparePublication } from '@/pages/PreparePublication';
import { BulkPublish } from '@/pages/BulkPublish';

export default function App() {
  return (
    <ProductProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/productos" element={<Products />} />
          <Route path="/productos/importar" element={<ImportProducts />} />
          <Route path="/productos/publicar-masivo" element={<BulkPublish />} />
          <Route path="/productos/:id" element={<ProductDetail />} />
          <Route path="/productos/:id/publicar" element={<PreparePublication />} />
          <Route path="/agregar-producto" element={<AddProduct />} />
          <Route path="/pendientes" element={<Pending />} />
          <Route path="/configuracion" element={<Settings />} />
        </Route>
      </Routes>
    </ProductProvider>
  );
}
