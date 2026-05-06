import { ReactNode, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { classNames } from '../lib/utils';

interface LayoutSimpleProps {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  backTo?: string;
  backLabel?: string;
  align?: 'left' | 'center';
}

export function LayoutSimple({
  title,
  description,
  children,
  footer,
  backTo,
  backLabel,
  align = 'left',
}: LayoutSimpleProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [title]);

  return (
    <div className="min-h-screen bg-[var(--color-page)] text-ink">
      <a
        href="#page-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-ink focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
      >
        Saltar al contenido
      </a>

      <main
        id="page-content"
        className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-6 sm:px-6 sm:py-8 lg:px-8"
      >
        <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {backTo ? (
            <nav aria-label="Navegación de página">
              <Link className="button-secondary text-sm" to={backTo}>
                {backLabel ?? 'Volver'}
              </Link>
            </nav>
          ) : (
            <span aria-hidden="true" />
          )}

          <Link className="button-secondary text-sm" to="/token">
            Gestionar token de acceso
          </Link>
        </div>

        <header
          className={classNames(
            'mb-8',
            align === 'center' && 'mx-auto max-w-3xl text-center',
          )}
        >
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="text-4xl font-semibold tracking-[-0.04em] text-ink outline-none sm:text-5xl"
          >
            {title}
          </h1>
          {description ? (
            <p
              className={classNames(
                'mt-3 max-w-2xl text-base leading-7 text-subtle',
                align === 'center' && 'mx-auto',
              )}
            >
              {description}
            </p>
          ) : null}
        </header>

        <div className="flex-1">{children}</div>
        {footer ? <div className="mt-8">{footer}</div> : null}
      </main>
    </div>
  );
}
