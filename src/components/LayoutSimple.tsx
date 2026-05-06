import { ReactNode, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { classNames } from '../lib/utils';

interface LayoutSimpleProps {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  backTo?: string;
  backLabel?: string;
  align?: 'left' | 'center';
  showSkipLink?: boolean;
  showTokenButton?: boolean;
  variant?: 'app' | 'plain';
}

export function LayoutSimple({
  title,
  description,
  children,
  footer,
  backTo,
  backLabel,
  align = 'left',
  showSkipLink = true,
  showTokenButton = true,
  variant = 'app',
}: LayoutSimpleProps) {
  const navigate = useNavigate();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [title]);

  return (
    <div className="min-h-screen bg-[var(--color-page)] text-ink">
      {showSkipLink ? (
        <a
          href="#page-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-ink focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
        >
          Saltar al contenido
        </a>
      ) : null}

      {variant === 'app' ? (
        <header className="bg-[var(--uoc-blue)] text-white">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
            <p className="text-lg font-semibold tracking-[-0.02em]">
              AccessibleCourse
            </p>
            <div className="flex flex-col gap-3 sm:flex-row">
              {backTo ? (
                <button
                  className="button-on-blue"
                  onClick={() => navigate(backTo)}
                  type="button"
                >
                  {backLabel ?? 'Volver'}
                </button>
              ) : null}
              {showTokenButton ? (
                <button
                  className="button-on-blue"
                  onClick={() => navigate('/token')}
                  type="button"
                >
                  Gestionar token de acceso
                </button>
              ) : null}
            </div>
          </div>
        </header>
      ) : null}

      <main
        id="page-content"
        className={classNames(
          'mx-auto flex w-full max-w-6xl flex-col px-4 py-8 sm:px-6 sm:py-10 lg:px-8',
          variant === 'plain' && 'min-h-screen justify-center',
          variant === 'app' && 'min-h-[calc(100vh-88px)]',
        )}
      >
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
