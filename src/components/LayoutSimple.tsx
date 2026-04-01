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
    <div className="min-h-screen bg-white text-ink">
      <a
        href="#contenido"
        className="absolute left-4 top-4 -translate-y-16 rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white focus:translate-y-0"
      >
        Saltar al contenido
      </a>

      <main
        id="contenido"
        className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-8 sm:px-10 sm:py-12"
      >
        <div className="mx-auto w-full max-w-4xl flex-1">
          <header className={classNames('mb-10', align === 'center' && 'text-center')}>
            {backTo ? (
              <Link className="button-secondary mb-8 text-sm" to={backTo}>
                {backLabel ?? 'Volver'}
              </Link>
            ) : null}

            <p className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-subtle">
              AccessibleCourse
            </p>
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-display-sm font-semibold text-ink outline-none sm:text-5xl sm:leading-[1.1]"
            >
              {title}
            </h1>
            {description ? (
              <p className="mt-4 max-w-2xl text-lg leading-8 text-subtle">{description}</p>
            ) : null}
          </header>

          {children}
        </div>

        {footer ? <div className="mx-auto mt-8 w-full max-w-4xl">{footer}</div> : null}
      </main>
    </div>
  );
}
