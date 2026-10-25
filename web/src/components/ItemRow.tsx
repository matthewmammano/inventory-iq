import { Text } from "@usefragments/ui";

import type { ItemListResponseItemResponse as Item } from "../api/types.gen";
import { ChevronRight } from "./icons/ChevronRight";

import "./ItemRow.css";

type ItemRowProps = {
  item: Item;
  onPick: (item: Item) => void;
};

/** One search result: the name, and the tags in the colors the agency chose. No on-hand count. */
export function ItemRow({ item, onPick }: ItemRowProps) {
  return (
    <li>
      <button type="button" className="iq-item-row" onClick={() => onPick(item)}>
        <Text as="strong" strong>
          {item.name}
        </Text>
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
        <span className="iq-item-chevron">
          <ChevronRight />
        </span>
      </button>
    </li>
  );
}
