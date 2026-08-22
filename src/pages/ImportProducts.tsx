import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Download, CheckCircle2, AlertTriangle } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { UploadDropzone } from '@/components/import/UploadDropzone';
import { ColumnMappingReview } from '@/components/import/ColumnMappingReview';
import { ImportSummaryCards, ImportProblemsTable } from '@/components/import/ImportSummaryTable';
import { DuplicatesReview } from '@/components/import/DuplicatesReview';
import { ProcessingProgress } from '@/components/import/ProcessingProgress';
import {
  buildRowResults,
  detectColumns,
  downloadExcelTemplate,
  findDuplicateGroups,
  parseSpreadsheetFile,
  resolveDuplicates,
  summarize,
} from '@/services/importService';
import { processBatch } from '@/services/aiService';
import { buildImportedProduct } from '@/services/productService';
import { useProducts } from '@/context/ProductContext';
import type { ColumnMapping, DuplicateGroup, ImportField, ImportRowResult, ParsedSpreadsheet } from '@/types/import';
import type { Product } from '@/types/product';

type Step = 'upload' | 'mapping' | 'summary' | 'duplicates' | 'processing' | 'done';

export function ImportProducts() {
  const navigate = useNavigate();
  const { importProducts } = useProducts();

  const [step, setStep] = useState<Step>('upload');
  const [error, setError] = useState<string | null>(null);
  const [parsed, setParsed] = useState<ParsedSpreadsheet | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping | null>(null);
  const [rowResults, setRowResults] = useState<ImportRowResult[]>([]);
  const [duplicateGroups, setDuplicateGroups] = useState<DuplicateGroup[]>([]);
  const [showProblems, setShowProblems] = useState(false);
  const [processedCount, setProcessedCount] = useState(0);
  const [importedProducts, setImportedProducts] = useState<Product[]>([]);

  const summary = useMemo(() => summarize(rowResults), [rowResults]);

  async function handleFile(file: File) {
    setError(null);
    try {
      const result = await parseSpreadsheetFile(file);
      if (result.rows.length === 0) {
        setError('No encontramos productos en este archivo. Revisa que tenga datos además del encabezado.');
        return;
      }
      setParsed(result);
      setMapping(detectColumns(result.headers));
      setStep('mapping');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos leer el archivo.');
    }
  }

  function handleMappingChange(field: ImportField, header: string | null) {
    setMapping((prev) => (prev ? { ...prev, [field]: header } : prev));
  }

  function handleConfirmMapping() {
    if (!parsed || !mapping) return;
    const results = buildRowResults(parsed.rows, mapping);
    setRowResults(results);
    setDuplicateGroups(findDuplicateGroups(results));
    setStep('summary');
  }

  function handleContinueFromSummary() {
    if (duplicateGroups.length > 0) {
      setStep('duplicates');
    } else {
      startProcessing(rowResults, new Set());
    }
  }

  function handleResolveDuplicate(clave: string, resolucion: DuplicateGroup['resolucion']) {
    setDuplicateGroups((prev) => prev.map((g) => (g.clave === clave ? { ...g, resolucion } : g)));
  }

  const allDuplicatesResolved = duplicateGroups.every((g) => g.resolucion !== null);

  function handleContinueFromDuplicates() {
    const excluded = resolveDuplicates(duplicateGroups);
    startProcessing(rowResults, excluded);
  }

  async function startProcessing(results: ImportRowResult[], excluded: Set<number>) {
    // Filas que efectivamente se pueden convertir en productos: tienen SKU y
    // nombre, y no fueron descartadas por la resolución de duplicados.
    const usable = results.filter((r) => r.sku && r.nombre && !excluded.has(r.rowIndex));

    setStep('processing');
    setProcessedCount(0);

    const processedInfos = await processBatch(
      usable.map((r) => ({ nombre: r.nombre, marca: r.marca, categoria: r.categoria, descripcion: r.descripcion })),
      (done) => setProcessedCount(done),
    );

    const products = usable.map((row, i) => buildImportedProduct(row, processedInfos[i]));
    setImportedProducts(products);
    setStep('done');
  }

  function handleFinish() {
    if (importedProducts.length > 0) {
      importProducts(importedProducts);
    }
    navigate('/productos');
  }

  function handleReset() {
    setStep('upload');
    setError(null);
    setParsed(null);
    setMapping(null);
    setRowResults([]);
    setDuplicateGroups([]);
    setShowProblems(false);
    setProcessedCount(0);
    setImportedProducts([]);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <button
        onClick={() => navigate('/productos')}
        className="mb-6 inline-flex items-center gap-2 text-base font-medium text-[--color-ink-900] hover:underline"
      >
        <ArrowLeft size={18} />
        Volver a productos
      </button>

      {step === 'upload' && (
        <Card className="p-6 lg:p-8">
          <h1 className="font-display text-2xl font-semibold text-[--color-ink-950]">Importar catálogo</h1>
          <p className="mt-2 text-base text-[--color-neutral-600]">
            Sube el archivo Excel de productos de tu librería. El sistema analizará automáticamente la información.
          </p>

          <div className="mt-6">
            <UploadDropzone onFile={handleFile} />
          </div>

          {error && <p className="mt-4 text-base text-[--color-err-600]">{error}</p>}

          <button
            type="button"
            onClick={() => downloadExcelTemplate()}
            className="mt-6 inline-flex items-center gap-2 text-base font-medium text-[--color-ink-900] hover:underline"
          >
            <Download size={18} />
            Descargar plantilla Excel
          </button>
        </Card>
      )}

      {step === 'mapping' && parsed && mapping && (
        <Card className="p-6 lg:p-8">
          <ColumnMappingReview headers={parsed.headers} mapping={mapping} rowCount={parsed.rows.length} onChange={handleMappingChange} />
          <div className="mt-8 flex gap-3">
            <Button onClick={handleConfirmMapping}>Continuar</Button>
            <Button variant="secondary" onClick={handleReset}>
              Cancelar
            </Button>
          </div>
        </Card>
      )}

      {step === 'summary' && (
        <Card className="p-6 lg:p-8">
          <h2 className="font-display text-2xl font-semibold text-[--color-ink-950]">Resultado de la importación</h2>
          <div className="mt-6">
            <ImportSummaryCards summary={summary} />
          </div>

          {showProblems && (
            <div className="mt-6">
              <ImportProblemsTable rows={rowResults} />
            </div>
          )}

          <div className="mt-8 flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => setShowProblems((s) => !s)}>
              {showProblems ? 'Ocultar productos con problemas' : 'Ver productos con problemas'}
            </Button>
            <Button onClick={handleContinueFromSummary}>Continuar</Button>
          </div>
        </Card>
      )}

      {step === 'duplicates' && (
        <Card className="p-6 lg:p-8">
          <DuplicatesReview groups={duplicateGroups} rows={rowResults} onResolve={handleResolveDuplicate} />
          <div className="mt-8 flex gap-3">
            <Button onClick={handleContinueFromDuplicates} disabled={!allDuplicatesResolved}>
              Continuar
            </Button>
          </div>
          {!allDuplicatesResolved && (
            <p className="mt-3 text-sm text-[--color-neutral-600]">Elige una opción para cada producto duplicado antes de continuar.</p>
          )}
        </Card>
      )}

      {step === 'processing' && (
        <Card className="p-6 lg:p-8">
          <ProcessingProgress processed={processedCount} total={Math.max(1, rowResults.filter((r) => r.sku && r.nombre).length)} />
        </Card>
      )}

      {step === 'done' && (
        <Card className="flex flex-col items-center gap-4 p-10 text-center">
          <CheckCircle2 size={44} className="text-[--color-ok-600]" />
          <h2 className="font-display text-2xl font-semibold text-[--color-ink-950]">Catálogo procesado</h2>
          <p className="text-base text-[--color-neutral-600]">
            {importedProducts.length.toLocaleString('es-CL')} productos quedaron listos en tu catálogo.
          </p>
          {rowResults.some((r) => !r.sku || !r.nombre) && (
            <p className="flex items-center gap-2 text-sm text-[--color-warn-600]">
              <AlertTriangle size={16} />
              Algunas filas no se pudieron importar por falta de SKU o nombre.
            </p>
          )}
          <div className="mt-2 flex gap-3">
            <Button onClick={handleFinish}>Ver productos</Button>
            <Button variant="secondary" onClick={handleReset}>
              Importar otro archivo
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
