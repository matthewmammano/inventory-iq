import type { ItemListResponseItemResponse as Item } from "../api/types.gen";

import "./ItemRow.css";

type ItemRowProps = {
  item: Item;
  onPick: (item: Item) => void;
};

/** One search result: the name on the left, the tags in the agency's own colors on the right. */
export function ItemRow({ item, onPick }: ItemRowProps) {
  return (
    <li>
      <button type="button" className="iq-item-row" onClick={() => onPick(item)}>
        <strong className="iq-item-name">{item.name}</strong>
        <span className="iq-item-tags">
          {item.tags.map((tag) => (
            <span
              key={tag.name}
              className="iq-item-tag"
              style={{ background: tag.color, color: tag.text_color, borderColor: tag.text_color }}
            >
              {tag.name}
            </span>
          ))}
        </span>
      </button>
    </li>
  );
}
