import { useNavigate } from 'react-router-dom';
import { Card } from '@/components/ui/Card';
import { ProductForm } from '@/components/products/ProductForm';
import { useProducts } from '@/context/ProductContext';
import type { ProductFormInput } from '@/types/product';

export function AddProduct() {
  const { addProduct } = useProducts();
  const navigate = useNavigate();

  function handleSubmit(input: ProductFormInput) {
    const product = addProduct(input);
    navigate(`/productos/${product.id}`);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <p className="mb-6 text-lg text-[--color-neutral-600]">
        Completa los datos del producto. Se guardará en tu catálogo local al presionar "Guardar producto".
      </p>
      <Card className="p-6 lg:p-8">
        <ProductForm submitLabel="Guardar producto" onSubmit={handleSubmit} onCancel={() => navigate('/productos')} />
      </Card>
    </div>
  );
}
